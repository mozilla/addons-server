# -*- coding: utf-8 -*-
import collections
import itertools
import json
import os
import posixpath
import re
import time
import urlparse
import uuid

from datetime import datetime
from operator import attrgetter

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, models, transaction
from django.db.models import F, Max, Q, signals as dbsignals
from django.dispatch import receiver
from django.utils.functional import cached_property
from django.utils import translation
from django.utils.translation import trans_real, ugettext_lazy as _

from django_extensions.db.fields.json import JSONField
from django_statsd.clients import statsd
from jinja2.filters import do_dictsort

import olympia.core.logger

from olympia import activity, amo, core
from olympia.access import acl
from olympia.addons.utils import (
    generate_addon_guid, get_creatured_ids, get_featured_ids)
from olympia.amo.decorators import use_master, write
from olympia.amo.models import (
    BasePreview, ManagerBase, manual_order, ModelBase, OnChangeMixin,
    SaveUpdateMixin, SlugField, TransformQuerySet)
from olympia.amo.templatetags import jinja_helpers
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import (
    AMOJSONEncoder, attach_trans_dict, cache_ns_key, chunked, find_language,
    send_mail, slugify, sorted_groupby, timer, to_language)
from olympia.constants.categories import CATEGORIES, CATEGORIES_BY_ID
from olympia.files.models import File
from olympia.files.utils import extract_translations, resolve_i18n_message
from olympia.ratings.models import Rating
from olympia.tags.models import Tag
from olympia.translations.fields import (
    LinkifiedField, PurifiedField, TranslatedField, Translation, save_signal)
from olympia.users.models import UserForeignKey, UserProfile
from olympia.versions.compare import version_int
from olympia.versions.models import inherit_nomination, Version, VersionPreview

from . import signals


log = olympia.core.logger.getLogger('z.addons')


MAX_SLUG_INCREMENT = 999
SLUG_INCREMENT_SUFFIXES = set(range(1, MAX_SLUG_INCREMENT + 1))


def get_random_slug():
    """Return a 20 character long random string"""
    return ''.join(str(uuid.uuid4()).split('-')[:-1])


def clean_slug(instance, slug_field='slug'):
    """Cleans a model instance slug.

    This strives to be as generic as possible but is only used
    by Add-ons at the moment.

    :param instance: The instance to clean the slug for.
    :param slug_field: The field where to get the currently set slug from.
    """
    slug = getattr(instance, slug_field, None) or instance.name

    if not slug:
        # Initialize the slug with what we have available: a name translation
        # or in last resort a random slug.
        translations = Translation.objects.filter(id=instance.name_id)
        if translations.exists():
            slug = translations[0]
        else:
            slug = get_random_slug()

    max_length = instance._meta.get_field(slug_field).max_length
    slug = slugify(slug)[:max_length]

    if DeniedSlug.blocked(slug):
        slug = slug[:max_length - 1] + '~'

    # The following trick makes sure we are using a manager that returns
    # all the objects, as otherwise we could have a slug clash on our hands.
    # Eg with the "Addon.objects" manager, which doesn't list deleted addons,
    # we could have a "clean" slug which is in fact already assigned to an
    # already existing (deleted) addon. Also, make sure we use the base class.
    manager = models.Manager()
    manager.model = instance._meta.proxy_for_model or instance.__class__

    qs = manager.values_list(slug_field, flat=True)  # Get list of all slugs.
    if instance.id:
        qs = qs.exclude(pk=instance.id)  # Can't clash with itself.

    # We first need to make sure there's a clash, before trying to find a
    # suffix that is available. Eg, if there's a "foo-bar" slug, "foo" is still
    # available.
    clash = qs.filter(**{slug_field: slug})

    if clash.exists():
        max_postfix_length = len(str(MAX_SLUG_INCREMENT))

        slug = slugify(slug)[:max_length - max_postfix_length]

        # There is a clash, so find a suffix that will make this slug unique.
        lookup = {'%s__startswith' % slug_field: slug}
        clashes = qs.filter(**lookup)

        prefix_len = len(slug)
        used_slug_numbers = [value[prefix_len:] for value in clashes]

        # find the next free slug number
        slug_numbers = {int(i) for i in used_slug_numbers if i.isdigit()}
        unused_numbers = SLUG_INCREMENT_SUFFIXES - slug_numbers

        if unused_numbers:
            num = min(unused_numbers)
        elif max_length is None:
            num = max(slug_numbers) + 1
        else:
            # This could happen. The current implementation (using
            # ``[:max_length -2]``) only works for the first 100 clashes in the
            # worst case (if the slug is equal to or longuer than
            # ``max_length - 2`` chars).
            # After that, {verylongslug}-100 will be trimmed down to
            # {verylongslug}-10, which is already assigned, but it's the last
            # solution tested.
            raise RuntimeError(
                'No suitable slug increment for {} found'.format(slug))

        slug = u'{slug}{postfix}'.format(slug=slug, postfix=num)

    setattr(instance, slug_field, slug)

    return instance


class AddonQuerySet(TransformQuerySet):
    def id_or_slug(self, val):
        """Get add-ons by id or slug."""
        if isinstance(val, basestring) and not val.isdigit():
            return self.filter(slug=val)
        return self.filter(id=val)

    def enabled(self):
        """Get add-ons that haven't been disabled by their developer(s)."""
        return self.filter(disabled_by_user=False)

    def public(self):
        """Get public add-ons only"""
        return self.filter(self.valid_q([amo.STATUS_PUBLIC]))

    def valid(self):
        """Get valid, enabled add-ons only"""
        return self.filter(self.valid_q(amo.VALID_ADDON_STATUSES))

    def valid_and_disabled_and_pending(self):
        """
        Get valid, pending, enabled and disabled add-ons.
        Used to allow pending theme pages to still be viewed.
        """
        statuses = (list(amo.VALID_ADDON_STATUSES) +
                    [amo.STATUS_DISABLED, amo.STATUS_PENDING])
        return (self.filter(Q(status__in=statuses) | Q(disabled_by_user=True))
                .exclude(type=amo.ADDON_EXTENSION,
                         _current_version__isnull=True))

    def featured(self, app, lang=None, type=None):
        """
        Filter for all featured add-ons for an application in all locales.
        """
        ids = get_featured_ids(app, lang, type)
        return manual_order(self.listed(app), ids, 'addons.id')

    def listed(self, app, *status):
        """
        Return add-ons that support a given ``app``, have a version with a file
        matching ``status`` and are not disabled.
        """
        if len(status) == 0:
            status = [amo.STATUS_PUBLIC]
        return self.filter(self.valid_q(status), appsupport__app=app.id)

    def valid_q(self, status=None, prefix=''):
        """
        Return a Q object that selects a valid Addon with the given statuses.

        An add-on is valid if not disabled and has a current version.
        ``prefix`` can be used if you're not working with Addon directly and
        need to hop across a join, e.g. ``prefix='addon__'`` in
        CollectionAddon.
        """
        if not status:
            status = [amo.STATUS_PUBLIC]

        def q(*args, **kw):
            if prefix:
                kw = dict((prefix + k, v) for k, v in kw.items())
            return Q(*args, **kw)

        return q(q(_current_version__isnull=False),
                 disabled_by_user=False, status__in=status)


class AddonManager(ManagerBase):

    def __init__(self, include_deleted=False):
        # DO NOT change the default value of include_deleted unless you've read
        # through the comment just above the Addon managers
        # declaration/instantiation and understand the consequences.
        ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_queryset(self):
        qs = super(AddonManager, self).get_queryset()
        qs = qs._clone(klass=AddonQuerySet)
        if not self.include_deleted:
            qs = qs.exclude(status=amo.STATUS_DELETED)
        return qs.transform(Addon.transformer)

    def id_or_slug(self, val):
        """Get add-ons by id or slug."""
        return self.get_queryset().id_or_slug(val)

    def enabled(self):
        """Get add-ons that haven't been disabled by their developer(s)."""
        return self.get_queryset().enabled()

    def public(self):
        """Get public add-ons only"""
        return self.get_queryset().public()

    def valid(self):
        """Get valid, enabled add-ons only"""
        return self.get_queryset().valid()

    def valid_and_disabled_and_pending(self):
        """
        Get valid, pending, enabled and disabled add-ons.
        Used to allow pending theme pages to still be viewed.
        """
        return self.get_queryset().valid_and_disabled_and_pending()

    def featured(self, app, lang=None, type=None):
        """
        Filter for all featured add-ons for an application in all locales.
        """
        return self.get_queryset().featured(app, lang=lang, type=type)

    def listed(self, app, *status):
        """
        Return add-ons that support a given ``app``, have a version with a file
        matching ``status`` and are not disabled.
        """
        return self.get_queryset().listed(app, *status)


class Addon(OnChangeMixin, ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES_ADDON

    guid = models.CharField(max_length=255, unique=True, null=True)
    slug = models.CharField(max_length=30, unique=True, null=True)
    name = TranslatedField(default=None)
    default_locale = models.CharField(max_length=10,
                                      default=settings.LANGUAGE_CODE,
                                      db_column='defaultlocale')

    type = models.PositiveIntegerField(
        choices=amo.ADDON_TYPE.items(), db_column='addontype_id',
        default=amo.ADDON_EXTENSION)
    status = models.PositiveIntegerField(
        choices=STATUS_CHOICES.items(), db_index=True, default=amo.STATUS_NULL)
    icon_type = models.CharField(max_length=25, blank=True,
                                 db_column='icontype')
    icon_hash = models.CharField(max_length=8, blank=True, null=True)
    homepage = TranslatedField()
    support_email = TranslatedField(db_column='supportemail')
    support_url = TranslatedField(db_column='supporturl')
    description = PurifiedField(short=False)

    summary = LinkifiedField()
    developer_comments = PurifiedField(db_column='developercomments')
    eula = PurifiedField()
    privacy_policy = PurifiedField(db_column='privacypolicy')

    average_rating = models.FloatField(max_length=255, default=0, null=True,
                                       db_column='averagerating')
    bayesian_rating = models.FloatField(default=0, db_index=True,
                                        db_column='bayesianrating')
    total_ratings = models.PositiveIntegerField(default=0,
                                                db_column='totalreviews')
    text_ratings_count = models.PositiveIntegerField(
        default=0, db_column='textreviewscount')
    weekly_downloads = models.PositiveIntegerField(
        default=0, db_column='weeklydownloads', db_index=True)
    total_downloads = models.PositiveIntegerField(
        default=0, db_column='totaldownloads')
    hotness = models.FloatField(default=0, db_index=True)

    average_daily_downloads = models.PositiveIntegerField(default=0)
    average_daily_users = models.PositiveIntegerField(default=0)

    last_updated = models.DateTimeField(
        db_index=True, null=True,
        help_text='Last time this add-on had a file/version update')

    disabled_by_user = models.BooleanField(default=False, db_index=True,
                                           db_column='inactive')
    view_source = models.BooleanField(default=True, db_column='viewsource')
    public_stats = models.BooleanField(default=False, db_column='publicstats')
    external_software = models.BooleanField(default=False,
                                            db_column='externalsoftware')
    dev_agreement = models.BooleanField(
        default=False, help_text="Has the dev agreement been signed?")
    auto_repackage = models.BooleanField(
        default=True, help_text='Automatically upgrade jetpack add-on to a '
                                'new sdk version?')

    target_locale = models.CharField(
        max_length=255, db_index=True, blank=True, null=True,
        help_text="For dictionaries and language packs")
    locale_disambiguation = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="For dictionaries and language packs")

    contributions = models.URLField(max_length=255, blank=True)

    authors = models.ManyToManyField('users.UserProfile', through='AddonUser',
                                     related_name='addons')
    categories = models.ManyToManyField('Category', through='AddonCategory')
    dependencies = models.ManyToManyField('self', symmetrical=False,
                                          through='AddonDependency',
                                          related_name='addons')

    _current_version = models.ForeignKey(Version, db_column='current_version',
                                         related_name='+', null=True,
                                         on_delete=models.SET_NULL)

    is_experimental = models.BooleanField(default=False,
                                          db_column='experimental')
    reputation = models.SmallIntegerField(default=0, null=True)
    requires_payment = models.BooleanField(default=False)

    # The order of those managers is very important:
    # The first one discovered, if it has "use_for_related_fields = True"
    # (which it has if it's inheriting `ManagerBase`), will
    # be used for relations like `version.addon`. We thus want one that is NOT
    # filtered in any case, we don't want a 500 if the addon is not found
    # (because it has the status amo.STATUS_DELETED for example).
    # The CLASS of the first one discovered will also be used for "many to many
    # relations" like `collection.addons`. In that case, we do want the
    # filtered version by default, to make sure we're not displaying stuff by
    # mistake. You thus want the CLASS of the first one to be filtered by
    # default.
    # We don't control the instantiation, but AddonManager sets include_deleted
    # to False by default, so filtering is enabled by default. This is also why
    # it's not repeated for 'objects' below.
    unfiltered = AddonManager(include_deleted=True)
    objects = AddonManager()

    class Meta:
        db_table = 'addons'
        index_together = [
            ['weekly_downloads', 'type'],
            ['created', 'type'],
            ['bayesian_rating', 'type'],
            ['last_updated', 'type'],
            ['average_daily_users', 'type'],
            ['type', 'status', 'disabled_by_user'],
        ]

    def __unicode__(self):
        return u'%s: %s' % (self.id, self.name)

    def __init__(self, *args, **kw):
        super(Addon, self).__init__(*args, **kw)

        if self.type == amo.ADDON_PERSONA:
            self.STATUS_CHOICES = Persona.STATUS_CHOICES

    def save(self, **kw):
        self.clean_slug()
        super(Addon, self).save(**kw)

    @classmethod
    def search_public(cls):
        """Legacy search method for public add-ons.

        Note that typically, code using this method do a search in ES but then
        will fetch the relevant objects from the database using Addon.objects,
        so deleted addons won't be returned no matter what ES returns. See
        amo.search.ES and amo.search.ObjectSearchResults for more details.

        In new code, use elasticsearch-dsl instead.
        """
        return cls.search().filter(
            is_disabled=False,
            status__in=amo.REVIEWED_STATUSES,
            current_version__exists=True)

    @use_master
    def clean_slug(self, slug_field='slug'):
        if self.status == amo.STATUS_DELETED:
            return

        clean_slug(self, slug_field)

    def is_soft_deleteable(self):
        return self.status or Version.unfiltered.filter(addon=self).exists()

    @transaction.atomic
    def delete(self, msg='', reason=''):
        # To avoid a circular import
        from . import tasks
        from olympia.versions import tasks as version_tasks
        # Check for soft deletion path. Happens only if the addon status isn't
        # 0 (STATUS_INCOMPLETE) with no versions.
        soft_deletion = self.is_soft_deleteable()
        if soft_deletion and self.status == amo.STATUS_DELETED:
            # We're already done.
            return

        id = self.id

        # Fetch previews before deleting the addon instance, so that we can
        # pass the list of files to delete to the delete_preview_files task
        # after the addon is deleted.
        previews = list(Preview.objects.filter(addon__id=id)
                        .values_list('id', flat=True))
        version_previews = list(
            VersionPreview.objects.filter(version__addon__id=id)
            .values_list('id', flat=True))

        if soft_deletion:
            # /!\ If we ever stop using soft deletion, and remove this code, we
            # need to make sure that the logs created below aren't cascade
            # deleted!

            log.debug('Deleting add-on: %s' % self.id)

            to = [settings.FLIGTAR]
            user = core.get_user()

            # Don't localize email to admins, use 'en-US' always.
            with translation.override(settings.LANGUAGE_CODE):
                # The types are lazy translated in apps/constants/base.py.
                atype = amo.ADDON_TYPE.get(self.type).upper()
            context = {
                'atype': atype,
                'authors': [u.email for u in self.authors.all()],
                'adu': self.average_daily_users,
                'guid': self.guid,
                'id': self.id,
                'msg': msg,
                'reason': reason,
                'name': self.name,
                'slug': self.slug,
                'total_downloads': self.total_downloads,
                'url': jinja_helpers.absolutify(self.get_url_path()),
                'user_str': ("%s, %s (%s)" % (user.display_name or
                                              user.username, user.email,
                                              user.id) if user else "Unknown"),
            }

            email_msg = u"""
            The following %(atype)s was deleted.
            %(atype)s: %(name)s
            URL: %(url)s
            DELETED BY: %(user_str)s
            ID: %(id)s
            GUID: %(guid)s
            AUTHORS: %(authors)s
            TOTAL DOWNLOADS: %(total_downloads)s
            AVERAGE DAILY USERS: %(adu)s
            NOTES: %(msg)s
            REASON GIVEN BY USER FOR DELETION: %(reason)s
            """ % context
            log.debug('Sending delete email for %(atype)s %(id)s' % context)
            subject = 'Deleting %(atype)s %(slug)s (%(id)d)' % context

            # If the add-on was disabled by Mozilla, add the guid to
            #  DeniedGuids to prevent resubmission after deletion.
            if self.status == amo.STATUS_DISABLED:
                try:
                    with transaction.atomic():
                        DeniedGuid.objects.create(guid=self.guid)
                except IntegrityError:
                    # If the guid is already in DeniedGuids, we are good.
                    pass

            # Update or NULL out various fields.
            models.signals.pre_delete.send(sender=Addon, instance=self)
            self._ratings.all().delete()
            # The last parameter is needed to automagically create an AddonLog.
            activity.log_create(amo.LOG.DELETE_ADDON, self.pk,
                                unicode(self.guid), self)
            self.update(status=amo.STATUS_DELETED, slug=None,
                        _current_version=None, modified=datetime.now())
            models.signals.post_delete.send(sender=Addon, instance=self)

            send_mail(subject, email_msg, recipient_list=to)
        else:
            # Real deletion path.
            super(Addon, self).delete()

        for preview in previews:
            tasks.delete_preview_files.delay(preview)
        for preview in version_previews:
            version_tasks.delete_preview_files.delay(preview)

        return True

    @classmethod
    def initialize_addon_from_upload(cls, data, upload, channel, user):
        fields = [field.name for field in cls._meta.get_fields()]
        guid = data.get('guid')
        old_guid_addon = None
        if guid:  # It's an extension.
            # Reclaim GUID from deleted add-on.
            try:
                old_guid_addon = Addon.unfiltered.get(guid=guid)
                old_guid_addon.update(guid=None)
            except ObjectDoesNotExist:
                pass

        generate_guid = (
            not data.get('guid', None) and
            data.get('is_webextension', False)
        )

        if generate_guid:
            data['guid'] = guid = generate_addon_guid()

        data = cls.resolve_webext_translations(data, upload)

        if channel == amo.RELEASE_CHANNEL_UNLISTED:
            data['slug'] = get_random_slug()

        addon = Addon(**dict((k, v) for k, v in data.items() if k in fields))

        addon.status = amo.STATUS_NULL
        locale_is_set = (addon.default_locale and
                         addon.default_locale in settings.AMO_LANGUAGES and
                         data.get('default_locale') == addon.default_locale)
        if not locale_is_set:
            addon.default_locale = to_language(trans_real.get_language())

        addon.save()

        if old_guid_addon:
            old_guid_addon.update(guid='guid-reused-by-pk-{}'.format(addon.pk))
            old_guid_addon.save()

        if user:
            AddonUser(addon=addon, user=user).save()
        return addon

    @classmethod
    def from_upload(cls, upload, platforms, source=None,
                    channel=amo.RELEASE_CHANNEL_LISTED, parsed_data=None,
                    user=None):
        """
        Create an Addon instance, a Version and corresponding File(s) from a
        FileUpload, a list of platform ids, a channel id and the
        parsed_data generated by parse_addon().

        Note that it's the caller's responsability to ensure the file is valid.
        We can't check for that here because an admin may have overridden the
        validation results.
        """
        assert parsed_data is not None

        addon = cls.initialize_addon_from_upload(
            parsed_data, upload, channel, user)

        if upload.validation_timeout:
            AddonReviewerFlags.objects.update_or_create(
                addon=addon, defaults={'needs_admin_code_review': True})
        Version.from_upload(upload, addon, platforms, source=source,
                            channel=channel, parsed_data=parsed_data)

        activity.log_create(amo.LOG.CREATE_ADDON, addon)
        log.debug('New addon %r from %r' % (addon, upload))

        return addon

    @classmethod
    def resolve_webext_translations(cls, data, upload):
        """Resolve all possible translations from an add-on.

        This returns a modified `data` dictionary accordingly with proper
        translations filled in.
        """
        default_locale = find_language(data.get('default_locale'))

        if not data.get('is_webextension') or not default_locale:
            # Don't change anything if we don't meet the requirements
            return data

        # find_language might have expanded short to full locale, so update it.
        data['default_locale'] = default_locale

        fields = ('name', 'homepage', 'summary')
        messages = extract_translations(upload)

        for field in fields:
            data[field] = {
                locale: resolve_i18n_message(
                    data[field],
                    locale=locale,
                    default_locale=default_locale,
                    messages=messages)
                for locale in messages
            }

        return data

    def get_url_path(self, more=False, add_prefix=True):
        if not self.current_version:
            return ''
        # If more=True you get the link to the ajax'd middle chunk of the
        # detail page.
        view = 'addons.detail_more' if more else 'addons.detail'
        return reverse(view, args=[self.slug], add_prefix=add_prefix)

    def get_dev_url(self, action='edit', args=None, prefix_only=False):
        args = args or []
        prefix = 'devhub'
        type_ = 'themes' if self.type == amo.ADDON_PERSONA else 'addons'
        if not prefix_only:
            prefix += '.%s' % type_
        view_name = '{prefix}.{action}'.format(prefix=prefix,
                                               action=action)
        return reverse(view_name, args=[self.slug] + args)

    def get_detail_url(self, action='detail', args=None):
        if args is None:
            args = []
        return reverse('addons.%s' % action, args=[self.slug] + args)

    def meet_the_dev_url(self):
        return reverse('addons.meet', args=[self.slug])

    @property
    def ratings_url(self):
        return reverse('addons.ratings.list', args=[self.slug])

    @classmethod
    def get_type_url(cls, type):
        try:
            type = amo.ADDON_SLUGS[type]
        except KeyError:
            return None
        return reverse('browse.%s' % type)

    def type_url(self):
        """The url for this add-on's type."""
        return Addon.get_type_url(self.type)

    def share_url(self):
        return reverse('addons.share', args=[self.slug])

    @cached_property
    def listed_authors(self):
        return UserProfile.objects.filter(
            addons=self,
            addonuser__listed=True).order_by('addonuser__position')

    @classmethod
    def get_fallback(cls):
        return cls._meta.get_field('default_locale')

    @property
    def ratings(self):
        return Rating.objects.filter(addon=self, reply_to=None)

    def get_category(self, app_id):
        categories = self.app_categories.get(amo.APP_IDS.get(app_id))
        return categories[0] if categories else None

    def language_ascii(self):
        lang = trans_real.to_language(self.default_locale)
        return settings.LANGUAGES.get(lang)

    @property
    def valid_file_statuses(self):
        if self.status == amo.STATUS_PUBLIC:
            return [amo.STATUS_PUBLIC]
        return amo.VALID_FILE_STATUSES

    def find_latest_public_listed_version(self):
        """Retrieve the latest public listed version of an addon.

        If the add-on is not public, it can return a listed version awaiting
        review (since non-public add-ons should not have public versions)."""
        if self.type == amo.ADDON_PERSONA:
            return
        try:
            statuses = self.valid_file_statuses
            status_list = ','.join(map(str, statuses))
            fltr = {
                'channel': amo.RELEASE_CHANNEL_LISTED,
                'files__status__in': statuses
            }
            return self.versions.filter(**fltr).extra(
                where=["""
                    NOT EXISTS (
                        SELECT 1 FROM files AS f2
                        WHERE f2.version_id = versions.id AND
                              f2.status NOT IN (%s))
                    """ % status_list])[0]

        except (IndexError, Version.DoesNotExist):
            return None

    def find_latest_version(self, channel, exclude=((amo.STATUS_DISABLED,))):
        """Retrieve the latest version of an add-on for the specified channel.

        If channel is None either channel is returned.

        Keyword arguments:
        exclude -- exclude versions for which all files have one
                   of those statuses (default STATUS_DISABLED)."""

        # If the add-on is deleted or hasn't been saved yet, it should not
        # have a latest version.
        if not self.id or self.status == amo.STATUS_DELETED:
            return None
        # We can't use .exclude(files__status=excluded_statuses) because that
        # would exclude a version if *any* of its files match but if there is
        # only one file that doesn't have one of the excluded statuses it
        # should be enough for that version to be considered.
        statuses_no_disabled = (
            set(amo.STATUS_CHOICES_FILE.keys()) - set(exclude))
        try:
            latest_qs = (
                Version.objects.filter(addon=self)
                       .filter(files__status__in=statuses_no_disabled))
            if channel is not None:
                latest_qs = latest_qs.filter(channel=channel)
            latest = latest_qs.latest()
            latest.addon = self
        except Version.DoesNotExist:
            latest = None
        return latest

    @write
    def update_version(self, ignore=None, _signal=True):
        """
        Update the current_version field on this add-on if necessary.

        Returns True if we updated the current_version field.

        The optional ``ignore`` parameter, if present, is a a version
        to not consider as part of the update, since it may be in the
        process of being deleted.

        Pass ``_signal=False`` if you want to no signals fired at all.

        """
        if self.is_persona():
            # Themes should only have a single version. So, if there is not
            # current version set, we just need to copy over the latest version
            # to current_version and we should never have to set it again.
            if not self._current_version:
                latest_version = self.find_latest_version(None)
                if latest_version:
                    self.update(_current_version=latest_version, _signal=False)
                return True
            return False

        new_current_version = self.find_latest_public_listed_version()
        updated = {}
        send_signal = False
        if self._current_version != new_current_version:
            updated['_current_version'] = new_current_version
            send_signal = True

        # update_version can be called by a post_delete signal (such
        # as File's) when deleting a version. If so, we should avoid putting
        # that version-being-deleted in any fields.
        if ignore is not None:
            updated = {k: v for k, v in updated.iteritems() if v != ignore}

        if updated:
            diff = [self._current_version, new_current_version]
            # Pass along _signal to the .update() to prevent it from firing
            # signals if we don't want them.
            updated['_signal'] = _signal
            try:
                self.update(**updated)
                if send_signal and _signal:
                    signals.version_changed.send(sender=self)
                log.info(u'Version changed from current: %s to %s '
                         u'for addon %s'
                         % tuple(diff + [self]))
            except Exception as e:
                log.error(u'Could not save version changes current: %s to %s '
                          u'for addon %s (%s)' %
                          tuple(diff + [self, e]))

        return bool(updated)

    def increment_theme_version_number(self):
        """Increment theme version number by 1."""
        latest_version = self.find_latest_version(None)
        version = latest_version or self.current_version
        version.version = str(float(version.version) + 1)
        # Set the current version.
        self.update(_current_version=version.save())

    def invalidate_d2c_versions(self):
        """Invalidates the cache of compatible versions.

        Call this when there is an event that may change what compatible
        versions are returned so they are recalculated.
        """
        key = cache_ns_key('d2c-versions:%s' % self.id, increment=True)
        log.info('Incrementing d2c-versions namespace for add-on [%s]: %s' % (
                 self.id, key))

    @property
    def current_version(self):
        """Return the latest public listed version of an addon

        If the add-on is not public, it can return a listed version awaiting
        review (since non-public add-ons should not have public versions).

        If the add-on has not been created yet or is deleted, it returns None.
        """
        if not self.id or self.status == amo.STATUS_DELETED:
            return None
        try:
            return self._current_version
        except ObjectDoesNotExist:
            pass
        return None

    @cached_property
    def latest_unlisted_version(self):
        """Shortcut property for Addon.find_latest_version(
        channel=RELEASE_CHANNEL_UNLISTED)."""
        return self.find_latest_version(channel=amo.RELEASE_CHANNEL_UNLISTED)

    @cached_property
    def binary(self):
        """Returns if the current version has binary files."""
        version = self.current_version
        if version:
            return version.files.filter(binary=True).exists()
        return False

    @cached_property
    def binary_components(self):
        """Returns if the current version has files with binary_components."""
        version = self.current_version
        if version:
            return version.files.filter(binary_components=True).exists()
        return False

    def get_icon_dir(self):
        return os.path.join(jinja_helpers.user_media_path('addon_icons'),
                            '%s' % (self.id / 1000))

    def get_icon_url(self, size, use_default=True):
        """
        Returns the addon's icon url according to icon_type.

        If it's a persona, it will return the icon_url of the associated
        Persona instance.

        If it's a theme and there is no icon set, it will return the default
        theme icon.

        If it's something else, it will return the default add-on icon, unless
        use_default is False, in which case it will return None.
        """
        icon_type_split = []
        if self.icon_type:
            icon_type_split = self.icon_type.split('/')

        # Get the closest allowed size without going over
        if (size not in amo.ADDON_ICON_SIZES and
                size >= amo.ADDON_ICON_SIZES[0]):
            size = [s for s in amo.ADDON_ICON_SIZES if s < size][-1]
        elif size < amo.ADDON_ICON_SIZES[0]:
            size = amo.ADDON_ICON_SIZES[0]

        # Figure out what to return for an image URL
        if self.type == amo.ADDON_PERSONA:
            return self.persona.icon_url
        if not self.icon_type:
            if self.type == amo.ADDON_THEME:
                icon = amo.ADDON_ICONS[amo.ADDON_THEME]
                return "%simg/icons/%s" % (settings.STATIC_URL, icon)
            else:
                if not use_default:
                    return None
                return self.get_default_icon_url(size)
        elif icon_type_split[0] == 'icon':
            return '{0}img/addon-icons/{1}-{2}.png'.format(
                settings.STATIC_URL,
                icon_type_split[1],
                size
            )
        else:
            # [1] is the whole ID, [2] is the directory
            split_id = re.match(r'((\d*?)\d{1,3})$', str(self.id))
            # Use the icon hash if we have one as the cachebusting suffix,
            # otherwise fall back to the add-on modification date.
            suffix = self.icon_hash or str(
                int(time.mktime(self.modified.timetuple())))
            path = '/'.join([
                split_id.group(2) or '0',
                '{0}-{1}.png?modified={2}'.format(self.id, size, suffix),
            ])
            return jinja_helpers.user_media_url('addon_icons') + path

    def get_default_icon_url(self, size):
        return '{0}img/addon-icons/{1}-{2}.png'.format(
            settings.STATIC_URL, 'default', size
        )

    @write
    def update_status(self, ignore_version=None):
        self.reload()

        if (self.status in [amo.STATUS_NULL, amo.STATUS_DELETED] or
                self.is_disabled or self.is_persona()):
            self.update_version(ignore=ignore_version)
            return

        versions = self.versions.filter(channel=amo.RELEASE_CHANNEL_LISTED)
        status = None
        if not versions.exists():
            status = amo.STATUS_NULL
            reason = 'no listed versions'
        elif not versions.filter(
                files__status__in=amo.VALID_FILE_STATUSES).exists():
            status = amo.STATUS_NULL
            reason = 'no listed version with valid file'
        elif (self.status == amo.STATUS_PUBLIC and
              not versions.filter(files__status=amo.STATUS_PUBLIC).exists()):
            if versions.filter(
                    files__status=amo.STATUS_AWAITING_REVIEW).exists():
                status = amo.STATUS_NOMINATED
                reason = 'only an unreviewed file'
            else:
                status = amo.STATUS_NULL
                reason = 'no reviewed files'
        elif self.status == amo.STATUS_PUBLIC:
            latest_version = self.find_latest_version(
                channel=amo.RELEASE_CHANNEL_LISTED)
            if (latest_version and latest_version.has_files and
                (latest_version.all_files[0].status ==
                 amo.STATUS_AWAITING_REVIEW)):
                # Addon is public, but its latest file is not (it's the case on
                # a new file upload). So, call update, to trigger watch_status,
                # which takes care of setting nomination time when needed.
                status = self.status
                reason = 'triggering watch_status'

        if status is not None:
            log.info('Changing add-on status [%s]: %s => %s (%s).'
                     % (self.id, self.status, status, reason))
            self.update(status=status)
            activity.log_create(amo.LOG.CHANGE_STATUS, self, self.status)

        self.update_version(ignore=ignore_version)

    @staticmethod
    def attach_related_versions(addons, addon_dict=None):
        if addon_dict is None:
            addon_dict = dict((a.id, a) for a in addons)

        all_ids = set(filter(None, (a._current_version_id for a in addons)))
        versions = list(Version.objects.filter(id__in=all_ids).order_by())
        for version in versions:
            try:
                addon = addon_dict[version.addon_id]
            except KeyError:
                log.debug('Version %s has an invalid add-on id.' % version.id)
                continue
            if addon._current_version_id == version.id:
                addon._current_version = version

            version.addon = addon

    @staticmethod
    def attach_listed_authors(addons, addon_dict=None):
        if addon_dict is None:
            addon_dict = dict((a.id, a) for a in addons)

        qs = (UserProfile.objects
              .filter(addons__in=addons, addonuser__listed=True)
              .extra(select={'addon_id': 'addons_users.addon_id',
                             'position': 'addons_users.position'}))
        qs = sorted(qs, key=lambda u: (u.addon_id, u.position))

        addons_with_authors = {
            addon_id: sorted(users, key=lambda author: author.position)
            for addon_id, users in itertools.groupby(
                qs, key=lambda u: u.addon_id
            )
        }

        for addon_id, addon in addon_dict.items():
            if addon_id in addons_with_authors:
                users = addons_with_authors[addon_id]
                addon_dict[addon_id].listed_authors = users
            else:
                addon_dict[addon_id].listed_authors = []

    @staticmethod
    def attach_previews(addons, addon_dict=None, no_transforms=False):
        if addon_dict is None:
            addon_dict = dict((a.id, a) for a in addons)

        qs = Preview.objects.filter(addon__in=addons,
                                    position__gte=0).order_by()
        if no_transforms:
            qs = qs.no_transforms()
        qs = sorted(qs, key=lambda x: (x.addon_id, x.position, x.created))
        for addon, previews in itertools.groupby(qs, lambda x: x.addon_id):
            addon_dict[addon].all_previews = list(previews)
        # FIXME: set all_previews to empty list on addons without previews.

    @staticmethod
    def attach_static_categories(addons, addon_dict=None):
        if addon_dict is None:
            addon_dict = dict((a.id, a) for a in addons)

        qs = (
            AddonCategory.objects
            .filter(addon__in=addon_dict.values())
            .values_list('addon_id', 'category_id'))

        for addon_id, cats_iter in itertools.groupby(qs, key=lambda x: x[0]):
            # The second value of each tuple in cats_iter are the category ids
            # we want.
            addon_dict[addon_id].category_ids = [c[1] for c in cats_iter]
            addon_dict[addon_id].all_categories = [
                CATEGORIES_BY_ID[cat_id] for cat_id
                in addon_dict[addon_id].category_ids
                if cat_id in CATEGORIES_BY_ID]

    @staticmethod
    @timer
    def transformer(addons):
        if not addons:
            return

        addon_dict = {a.id: a for a in addons}

        # Attach categories. This needs to be done before separating addons
        # from personas, because Personas need categories for the theme_data
        # JSON dump, rest of the add-ons need the first category to be
        # displayed in detail page / API.
        Addon.attach_static_categories(addons, addon_dict=addon_dict)

        # Set _current_version and attach listed authors.
        # Do this before splitting off personas and addons because
        # it needs to be attached to both.
        Addon.attach_related_versions(addons, addon_dict=addon_dict)
        Addon.attach_listed_authors(addons, addon_dict=addon_dict)

        personas = [a for a in addons if a.type == amo.ADDON_PERSONA]
        addons = [a for a in addons if a.type != amo.ADDON_PERSONA]

        # Persona-specific stuff
        for persona in Persona.objects.filter(addon__in=personas):
            addon = addon_dict[persona.addon_id]
            addon.persona = persona

        # Attach previews.
        Addon.attach_previews(addons, addon_dict=addon_dict)

        return addon_dict

    def show_adu(self):
        return self.type != amo.ADDON_SEARCH

    @property
    def icon_url(self):
        return self.get_icon_url(32)

    def authors_other_addons(self, app=None):
        """
        Return other addons by the author(s) of this addon,
        optionally takes an app.
        """
        if app:
            qs = Addon.objects.listed(app)
        else:
            qs = Addon.objects.valid()
        return (qs.exclude(id=self.id)
                  .filter(addonuser__listed=True,
                          authors__in=self.listed_authors)
                  .distinct())

    @property
    def contribution_url(self, lang=settings.LANGUAGE_CODE,
                         app=settings.DEFAULT_APP):
        return reverse('addons.contribute', args=[self.slug])

    @property
    def thumbnail_url(self):
        """
        Returns the addon's thumbnail url or a default.
        """
        try:
            preview = self.all_previews[0]
            return preview.thumbnail_url
        except IndexError:
            return settings.STATIC_URL + '/img/icons/no-preview.png'

    def can_request_review(self):
        """Return whether an add-on can request a review or not."""
        if (self.is_disabled or
                self.status in (amo.STATUS_PUBLIC,
                                amo.STATUS_NOMINATED,
                                amo.STATUS_DELETED)):
            return False

        latest_version = self.find_latest_version(amo.RELEASE_CHANNEL_LISTED,
                                                  exclude=())

        return (latest_version is not None and
                latest_version.files.exists() and
                not any(file.reviewed for file in latest_version.all_files))

    def is_persona(self):
        return self.type == amo.ADDON_PERSONA

    @property
    def is_disabled(self):
        """True if this Addon is disabled.

        It could be disabled by an admin or disabled by the developer
        """
        return self.status == amo.STATUS_DISABLED or self.disabled_by_user

    @property
    def is_deleted(self):
        return self.status == amo.STATUS_DELETED

    def is_unreviewed(self):
        return self.status in amo.UNREVIEWED_ADDON_STATUSES

    def is_public(self):
        return self.status == amo.STATUS_PUBLIC and not self.disabled_by_user

    def has_complete_metadata(self, has_listed_versions=None):
        """See get_required_metadata for has_listed_versions details."""
        return all(self.get_required_metadata(
            has_listed_versions=has_listed_versions))

    def get_required_metadata(self, has_listed_versions=None):
        """If has_listed_versions is not specified this method will return the
        current (required) metadata (truthy values if present) for this Addon.

        If has_listed_versions is specified then the method will act as if
        Addon.has_listed_versions() returns that value. Used to predict if the
        addon will require extra metadata before a version is created."""
        if has_listed_versions is None:
            has_listed_versions = self.has_listed_versions()
        if not has_listed_versions:
            # Add-ons with only unlisted versions have no required metadata.
            return []
        # We need to find out if the add-on has a license set. We prefer to
        # check the current_version first because that's what would be used for
        # public pages, but if there isn't any listed version will do.
        version = self.current_version or self.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED, exclude=())
        return [
            self.all_categories,
            self.summary,
            (version and version.license),
        ]

    def should_redirect_to_submit_flow(self):
        return (
            self.status == amo.STATUS_NULL and
            not self.has_complete_metadata() and
            self.find_latest_version(channel=amo.RELEASE_CHANNEL_LISTED))

    def is_pending(self):
        return self.status == amo.STATUS_PENDING

    def is_rejected(self):
        return self.status == amo.STATUS_REJECTED

    def can_be_deleted(self):
        return not self.is_deleted

    def has_listed_versions(self):
        return self.versions.filter(
            channel=amo.RELEASE_CHANNEL_LISTED).exists()

    def has_unlisted_versions(self):
        return self.versions.filter(
            channel=amo.RELEASE_CHANNEL_UNLISTED).exists()

    @classmethod
    def featured_random(cls, app, lang):
        return get_featured_ids(app, lang)

    @property
    def is_restart_required(self):
        """Whether the add-on current version requires a browser restart to
        work."""
        return (
            self.current_version and self.current_version.is_restart_required)

    def is_featured(self, app=None, lang=None):
        """Is add-on globally featured for this app and language?"""
        return self.id in get_featured_ids(app, lang)

    def get_featured_by_app(self):
        qset = (self.collections.filter(featuredcollection__isnull=False)
                .distinct().values_list('featuredcollection__application',
                                        'featuredcollection__locale'))
        out = collections.defaultdict(set)
        for app, locale in qset:
            out[app].add(locale)
        return out

    def has_full_profile(self):
        pass

    def has_profile(self):
        pass

    @cached_property
    def tags_partitioned_by_developer(self):
        """Returns a tuple of developer tags and user tags for this addon."""
        tags = self.tags.not_denied()
        if self.is_persona:
            return [], tags
        user_tags = tags.exclude(addon_tags__user__in=self.listed_authors)
        dev_tags = tags.exclude(id__in=[t.id for t in user_tags])
        return dev_tags, user_tags

    @cached_property
    def compatible_apps(self):
        """Shortcut to get compatible apps for the current version."""
        if self.current_version:
            return self.current_version.compatible_apps
        else:
            return {}

    def accepts_compatible_apps(self):
        """True if this add-on lists compatible apps."""
        return self.type not in amo.NO_COMPAT

    def incompatible_latest_apps(self):
        """Returns a list of applications with which this add-on is
        incompatible (based on the latest version of each app).

        """
        return [app for app, ver in self.compatible_apps.items() if ver and
                version_int(ver.max.version) < version_int(app.latest_version)]

    def has_author(self, user):
        """True if ``user`` is an author of the add-on."""
        if user is None or user.is_anonymous():
            return False
        return AddonUser.objects.filter(addon=self, user=user).exists()

    @property
    def takes_contributions(self):
        pass

    @classmethod
    def _last_updated_queries(cls):
        """
        Get the queries used to calculate addon.last_updated.
        """
        status_change = Max('versions__files__datestatuschanged')
        public = (
            Addon.objects.filter(
                status=amo.STATUS_PUBLIC,
                versions__files__status=amo.STATUS_PUBLIC)
            .exclude(type=amo.ADDON_PERSONA)
            .values('id').annotate(last_updated=status_change))

        stati = amo.VALID_ADDON_STATUSES
        exp = (Addon.objects.exclude(status__in=stati)
               .filter(versions__files__status__in=amo.VALID_FILE_STATUSES)
               .values('id')
               .annotate(last_updated=Max('versions__files__created')))

        personas = (Addon.objects.filter(type=amo.ADDON_PERSONA)
                    .extra(select={'last_updated': 'created'}))
        return dict(public=public, exp=exp, personas=personas)

    @cached_property
    def all_categories(self):
        return filter(
            None, [cat.to_static_category() for cat in self.categories.all()])

    @cached_property
    def current_previews(self):
        """Previews for the current version, or all of them if not a
        static theme."""
        if self.has_per_version_previews:
            if self.current_version:
                return self.current_version.previews.all()
            return []
        else:
            return self.all_previews

    @cached_property
    def all_previews(self):
        """Exclude promo graphics."""
        return list(self.previews.exclude(position=-1))

    @property
    def has_per_version_previews(self):
        return self.type == amo.ADDON_STATICTHEME

    @property
    def app_categories(self):
        app_cats = {}
        categories = sorted_groupby(
            sorted(self.all_categories, key=attrgetter('weight', 'name')),
            key=lambda x: amo.APP_IDS.get(x.application))
        for app, cats in categories:
            app_cats[app] = list(cats)
        return app_cats

    def remove_locale(self, locale):
        """NULLify strings in this locale for the add-on and versions."""
        for o in itertools.chain([self], self.versions.all()):
            Translation.objects.remove_for(o, locale)

    def get_localepicker(self):
        """For language packs, gets the contents of localepicker."""
        if (self.type == amo.ADDON_LPAPP and
                self.status == amo.STATUS_PUBLIC and
                self.current_version):
            files = (self.current_version.files
                         .filter(platform=amo.PLATFORM_ANDROID.id))
            try:
                return unicode(files[0].get_localepicker(), 'utf-8')
            except IndexError:
                pass
        return ''

    def can_review(self, user):
        """Check whether the user should be prompted to add a review or not."""
        return not user.is_authenticated() or not self.has_author(user)

    @property
    def all_dependencies(self):
        """Return all the (valid) add-ons this add-on depends on."""
        return list(self.dependencies.valid().all()[:3])

    def check_ownership(self, request, require_owner, require_author,
                        ignore_disabled, admin):
        """
        Used by acl.check_ownership to see if request.user has permissions for
        the addon.
        """
        if require_author:
            require_owner = False
            ignore_disabled = True
            admin = False
        return acl.check_addon_ownership(request, self, admin=admin,
                                         dev=(not require_owner),
                                         ignore_disabled=ignore_disabled)

    @property
    def feature_compatibility(self):
        try:
            feature_compatibility = self.addonfeaturecompatibility
        except AddonFeatureCompatibility.DoesNotExist:
            # If it does not exist, return a blank one, no need to create. It's
            # the caller responsibility to create when needed to avoid
            # unexpected database writes.
            feature_compatibility = AddonFeatureCompatibility()
        return feature_compatibility

    def should_show_permissions(self, version=None):
        version = version or self.current_version
        return (self.type == amo.ADDON_EXTENSION and
                version and version.all_files[0] and
                (not version.all_files[0].is_webextension or
                 version.all_files[0].webext_permissions))

    @property
    def needs_admin_code_review(self):
        try:
            return self.addonreviewerflags.needs_admin_code_review
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def needs_admin_content_review(self):
        try:
            return self.addonreviewerflags.needs_admin_content_review
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def needs_admin_theme_review(self):
        try:
            return self.addonreviewerflags.needs_admin_theme_review
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def auto_approval_disabled(self):
        try:
            return self.addonreviewerflags.auto_approval_disabled
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def pending_info_request(self):
        try:
            return self.addonreviewerflags.pending_info_request
        except AddonReviewerFlags.DoesNotExist:
            return None

    @property
    def expired_info_request(self):
        info_request = self.pending_info_request
        return info_request and info_request < datetime.now()


dbsignals.pre_save.connect(save_signal, sender=Addon,
                           dispatch_uid='addon_translations')


@receiver(signals.version_changed, dispatch_uid='version_changed')
def version_changed(sender, **kw):
    from . import tasks
    tasks.version_changed.delay(sender.id)


@receiver(dbsignals.post_save, sender=Addon,
          dispatch_uid='addons.search.index')
def update_search_index(sender, instance, **kw):
    from . import tasks
    if not kw.get('raw'):
        tasks.index_addons.delay([instance.id])


@Addon.on_change
def watch_status(old_attr=None, new_attr=None, instance=None,
                 sender=None, **kwargs):
    """
    Set nomination date if the addon is new in queue or updating.

    The nomination date cannot be reset, say, when a developer cancels
    their request for review and re-requests review.

    If a version is rejected after nomination, the developer has
    to upload a new version.

    """
    if old_attr is None:
        old_attr = {}
    if new_attr is None:
        new_attr = {}
    new_status = new_attr.get('status')
    old_status = old_attr.get('status')
    latest_version = instance.find_latest_version(
        channel=amo.RELEASE_CHANNEL_LISTED)

    # Update the author's account profile visibility
    if new_status != old_status:
        [author.update_is_public() for author in instance.authors.all()]

    if (new_status not in amo.VALID_ADDON_STATUSES or
            not new_status or not latest_version):
        return

    if old_status not in amo.UNREVIEWED_ADDON_STATUSES:
        # New: will (re)set nomination only if it's None.
        latest_version.reset_nomination_time()
    elif latest_version.has_files:
        # Updating: inherit nomination from last nominated version.
        # Calls `inherit_nomination` manually given that signals are
        # deactivated to avoid circular calls.
        inherit_nomination(None, latest_version)


@Addon.on_change
def watch_disabled(old_attr=None, new_attr=None, instance=None, sender=None,
                   **kwargs):
    if old_attr is None:
        old_attr = {}
    if new_attr is None:
        new_attr = {}
    attrs = dict((k, v) for k, v in old_attr.items()
                 if k in ('disabled_by_user', 'status'))
    if Addon(**attrs).is_disabled and not instance.is_disabled:
        for f in File.objects.filter(version__addon=instance.id):
            f.unhide_disabled_file()
    if instance.is_disabled and not Addon(**attrs).is_disabled:
        for f in File.objects.filter(version__addon=instance.id):
            f.hide_disabled_file()


def attach_translations(addons):
    """Put all translations into a translations dict."""
    attach_trans_dict(Addon, addons)


def attach_tags(addons):
    addon_dict = dict((a.id, a) for a in addons)
    qs = (Tag.objects.not_denied().filter(addons__in=addon_dict)
          .values_list('addons__id', 'tag_text'))
    for addon, tags in sorted_groupby(qs, lambda x: x[0]):
        addon_dict[addon].tag_list = [t[1] for t in tags]


class AddonReviewerFlags(ModelBase):
    addon = models.OneToOneField(
        Addon, primary_key=True, on_delete=models.CASCADE)
    needs_admin_code_review = models.BooleanField(default=False)
    needs_admin_content_review = models.BooleanField(default=False)
    needs_admin_theme_review = models.BooleanField(default=False)
    auto_approval_disabled = models.BooleanField(default=False)
    pending_info_request = models.DateTimeField(default=None, null=True)
    notified_about_expiring_info_request = models.BooleanField(default=False)


class Persona(models.Model):
    """Personas-specific additions to the add-on model."""
    STATUS_CHOICES = amo.STATUS_CHOICES_PERSONA

    addon = models.OneToOneField(Addon, null=True)
    persona_id = models.PositiveIntegerField(db_index=True)
    # name: deprecated in favor of Addon model's name field
    # description: deprecated, ditto
    header = models.CharField(max_length=64, null=True)
    footer = models.CharField(max_length=64, null=True)
    accentcolor = models.CharField(max_length=10, null=True)
    textcolor = models.CharField(max_length=10, null=True)
    author = models.CharField(max_length=255, null=True)
    display_username = models.CharField(max_length=255, null=True)
    submit = models.DateTimeField(null=True)
    approve = models.DateTimeField(null=True)
    movers = models.FloatField(null=True, db_index=True)
    popularity = models.IntegerField(null=False, default=0, db_index=True)
    license = models.PositiveIntegerField(
        choices=amo.PERSONA_LICENSES_CHOICES, null=True, blank=True)

    # To spot duplicate submissions.
    checksum = models.CharField(max_length=64, blank=True, default='')
    dupe_persona = models.ForeignKey('self', null=True)

    class Meta:
        db_table = 'personas'

    def __unicode__(self):
        return unicode(self.addon.name)

    def is_new(self):
        return self.persona_id == 0

    def _image_url(self, filename):
        host = jinja_helpers.user_media_url('addons')
        image_url = posixpath.join(host, str(self.addon.id), filename or '')
        if self.checksum:
            modified = self.checksum[:8]
        elif self.addon.modified is not None:
            modified = int(time.mktime(self.addon.modified.timetuple()))
        else:
            modified = 0
        return '%s?modified=%s' % (image_url, modified)

    def _image_path(self, filename):
        return os.path.join(jinja_helpers.user_media_path('addons'),
                            str(self.addon.id), filename)

    @cached_property
    def thumb_url(self):
        """
        Handles deprecated GetPersonas URL.
        In days of yore, preview.jpg used to be a separate image.
        In modern days, we use the same image for big preview + thumb.
        """
        if self.is_new():
            return self._image_url('preview.png')
        else:
            return self._image_url('preview.jpg')

    @cached_property
    def thumb_path(self):
        """
        Handles deprecated GetPersonas path.
        In days of yore, preview.jpg used to be a separate image.
        In modern days, we use the same image for big preview + thumb.
        """
        if self.is_new():
            return self._image_path('preview.png')
        else:
            return self._image_path('preview.jpg')

    @cached_property
    def icon_url(self):
        """URL to personas square preview."""
        if self.is_new():
            return self._image_url('icon.png')
        else:
            return self._image_url('preview_small.jpg')

    @cached_property
    def icon_path(self):
        """Path to personas square preview."""
        if self.is_new():
            return self._image_path('icon.png')
        else:
            return self._image_path('preview_small.jpg')

    @cached_property
    def preview_url(self):
        """URL to Persona's big, 680px, preview."""
        if self.is_new():
            return self._image_url('preview.png')
        else:
            return self._image_url('preview_large.jpg')

    @cached_property
    def preview_path(self):
        """Path to Persona's big, 680px, preview."""
        if self.is_new():
            return self._image_path('preview.png')
        else:
            return self._image_path('preview_large.jpg')

    @cached_property
    def header_url(self):
        return self._image_url(self.header)

    @cached_property
    def footer_url(self):
        return self.footer and self._image_url(self.footer) or ''

    @cached_property
    def header_path(self):
        return self._image_path(self.header)

    @cached_property
    def footer_path(self):
        return self.footer and self._image_path(self.footer) or ''

    @cached_property
    def update_url(self):
        locale = settings.LANGUAGE_URL_MAP.get(trans_real.get_language())
        return settings.NEW_PERSONAS_UPDATE_URL % {
            'locale': locale or settings.LANGUAGE_CODE,
            'id': self.addon.id
        }

    @cached_property
    def theme_data(self):
        """Theme JSON Data for Browser/extension preview."""
        def hexcolor(color):
            return ('#%s' % color) if color else None

        addon = self.addon
        return {
            'id': unicode(self.addon.id),  # Personas dislikes ints
            'name': unicode(addon.name),
            'accentcolor': hexcolor(self.accentcolor),
            'textcolor': hexcolor(self.textcolor),
            'category': (unicode(addon.all_categories[0].name) if
                         addon.all_categories else ''),
            # TODO: Change this to be `addons_users.user.display_name`.
            'author': self.display_username,
            'description': (unicode(addon.description)
                            if addon.description is not None
                            else addon.description),
            'header': self.header_url,
            'footer': self.footer_url or '',
            'headerURL': self.header_url,
            'footerURL': self.footer_url or '',
            'previewURL': self.preview_url,
            'iconURL': self.icon_url,
            'updateURL': self.update_url,
            'detailURL': jinja_helpers.absolutify(self.addon.get_url_path()),
            'version': '1.0'
        }

    @property
    def json_data(self):
        """Persona JSON Data for Browser/extension preview."""
        return json.dumps(self.theme_data,
                          separators=(',', ':'), cls=AMOJSONEncoder)

    def authors_other_addons(self, app=None):
        """
        Return other addons by the author(s) of this addon,
        optionally takes an app.
        """
        qs = (Addon.objects.valid()
                           .exclude(id=self.addon.id)
                           .filter(type=amo.ADDON_PERSONA))
        return (qs.filter(addonuser__listed=True,
                          authors__in=self.addon.listed_authors)
                  .distinct())

    @cached_property
    def listed_authors(self):
        return self.addon.listed_authors


class MigratedLWT(OnChangeMixin, ModelBase):
    lightweight_theme = models.ForeignKey(
        Addon, unique=True, related_name='migrated_to_static_theme')
    getpersonas_id = models.PositiveIntegerField(db_index=True)
    static_theme = models.ForeignKey(
        Addon, unique=True, related_name='migrated_from_lwt')

    class Meta:
        db_table = 'migrated_personas'

    def __init__(self, *args, **kw):
        super(MigratedLWT, self).__init__(*args, **kw)
        self.getpersonas_id = self.lightweight_theme.persona.persona_id


class AddonCategory(models.Model):
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    category = models.ForeignKey('Category')
    feature = models.BooleanField(default=False)
    feature_locales = models.CharField(max_length=255, default='', null=True)

    class Meta:
        db_table = 'addons_categories'
        unique_together = ('addon', 'category')

    @classmethod
    def creatured_random(cls, category, lang):
        return get_creatured_ids(category, lang)


class AddonUser(OnChangeMixin, SaveUpdateMixin, models.Model):
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    user = UserForeignKey()
    role = models.SmallIntegerField(default=amo.AUTHOR_ROLE_OWNER,
                                    choices=amo.AUTHOR_CHOICES)
    listed = models.BooleanField(_(u'Listed'), default=True)
    position = models.IntegerField(default=0)

    def __init__(self, *args, **kwargs):
        super(AddonUser, self).__init__(*args, **kwargs)
        self._original_role = self.role
        self._original_user_id = self.user_id

    class Meta:
        db_table = 'addons_users'


@AddonUser.on_change
def watch_addon_user(old_attr=None, new_attr=None, instance=None, sender=None,
                     **kwargs):
    instance.user.update_is_public()
    # Update ES because authors is included.
    update_search_index(sender=sender, instance=instance.addon, **kwargs)


class AddonDependency(models.Model):
    addon = models.ForeignKey(Addon, related_name='addons_dependencies')
    dependent_addon = models.ForeignKey(Addon, related_name='dependent_on')

    class Meta:
        db_table = 'addons_dependencies'
        unique_together = ('addon', 'dependent_addon')


class AddonFeatureCompatibility(ModelBase):
    addon = models.OneToOneField(
        Addon, primary_key=True, on_delete=models.CASCADE)
    e10s = models.PositiveSmallIntegerField(
        choices=amo.E10S_COMPATIBILITY_CHOICES, default=amo.E10S_UNKNOWN)

    def __unicode__(self):
        return unicode(self.addon) if self.pk else u""

    def get_e10s_classname(self):
        return amo.E10S_COMPATIBILITY_CHOICES_API[self.e10s]


class AddonApprovalsCounter(ModelBase):
    """Model holding a counter of the number of times a listed version
    belonging to an add-on has been approved by a human. Reset everytime a
    listed version is auto-approved for this add-on.

    Holds 2 additional date fields:
    - last_human_review, the date of the last time a human fully reviewed the
      add-on
    - last_content_review, the date of the last time a human fully reviewed the
      add-on content (not code).
    """
    addon = models.OneToOneField(
        Addon, primary_key=True, on_delete=models.CASCADE)
    counter = models.PositiveIntegerField(default=0)
    last_human_review = models.DateTimeField(null=True)
    last_content_review = models.DateTimeField(null=True)

    def __unicode__(self):
        return u'%s: %d' % (unicode(self.pk), self.counter) if self.pk else u''

    @classmethod
    def increment_for_addon(cls, addon):
        """
        Increment approval counter for the specified addon, setting the last
        human review date and last content review date to now.
        If an AddonApprovalsCounter already exists, it updates it, otherwise it
        creates and saves a new instance.
        """
        now = datetime.now()
        data = {
            'counter': 1,
            'last_human_review': now,
            'last_content_review': now,
        }
        obj, created = cls.objects.get_or_create(
            addon=addon, defaults=data)
        if not created:
            data['counter'] = F('counter') + 1
            obj.update(**data)
        return obj

    @classmethod
    def reset_for_addon(cls, addon):
        """
        Reset the approval counter (but not the dates) for the specified addon.
        """
        obj, created = cls.objects.update_or_create(
            addon=addon, defaults={'counter': 0})
        return obj

    @classmethod
    def approve_content_for_addon(cls, addon):
        """
        Set last_content_review for this addon.
        """
        obj, created = cls.objects.update_or_create(
            addon=addon, defaults={'last_content_review': datetime.now()})
        return obj


class DeniedGuid(ModelBase):
    guid = models.CharField(max_length=255, unique=True)
    comments = models.TextField(default='', blank=True)

    class Meta:
        db_table = 'denied_guids'

    def __unicode__(self):
        return self.guid


class Category(OnChangeMixin, ModelBase):
    # Old name translations, we now have constants translated via gettext, but
    # this is for backwards-compatibility, for categories which have a weird
    # type/application/slug combo that is not in the constants.
    db_name = TranslatedField(db_column='name')
    slug = SlugField(max_length=50,
                     help_text='Used in Category URLs.')
    type = models.PositiveIntegerField(db_column='addontype_id',
                                       choices=do_dictsort(amo.ADDON_TYPE))
    application = models.PositiveIntegerField(choices=amo.APPS_CHOICES,
                                              null=True, blank=True,
                                              db_column='application_id')
    count = models.IntegerField('Addon count', default=0)
    weight = models.IntegerField(
        default=0, help_text='Category weight used in sort ordering')
    misc = models.BooleanField(default=False)

    addons = models.ManyToManyField(Addon, through='AddonCategory')

    class Meta:
        db_table = 'categories'
        verbose_name_plural = 'Categories'

    @property
    def name(self):
        try:
            value = CATEGORIES[self.application][self.type][self.slug].name
        except KeyError:
            # If we can't find the category in the constants dict, fall back
            # to the db field.
            value = self.db_name
        return unicode(value)

    def __unicode__(self):
        return unicode(self.name)

    def get_url_path(self):
        try:
            type = amo.ADDON_SLUGS[self.type]
        except KeyError:
            type = amo.ADDON_SLUGS[amo.ADDON_EXTENSION]
        return reverse('browse.%s' % type, args=[self.slug])

    def to_static_category(self):
        """Return the corresponding StaticCategory instance from a Category."""
        try:
            staticcategory = CATEGORIES[self.application][self.type][self.slug]
        except KeyError:
            staticcategory = None
        return staticcategory

    @classmethod
    def from_static_category(cls, static_category, save=False):
        """Return a Category instance created from a StaticCategory.

        Does not save it into the database by default. Useful in tests."""
        # we need to drop description as it's a StaticCategory only property.
        _dict = dict(static_category.__dict__)
        del _dict['description']
        if save:
            category, _ = Category.objects.get_or_create(
                id=static_category.id, defaults=_dict)
            return category
        else:
            return cls(**_dict)


dbsignals.pre_save.connect(save_signal, sender=Category,
                           dispatch_uid='category_translations')


class Preview(BasePreview, ModelBase):
    addon = models.ForeignKey(Addon, related_name='previews')
    caption = TranslatedField()
    position = models.IntegerField(default=0)
    sizes = JSONField(default={})

    class Meta:
        db_table = 'previews'
        ordering = ('position', 'created')


dbsignals.pre_save.connect(save_signal, sender=Preview,
                           dispatch_uid='preview_translations')


models.signals.post_delete.connect(Preview.delete_preview_files,
                                   sender=Preview,
                                   dispatch_uid='delete_preview_files')


class AppSupport(ModelBase):
    """Cache to tell us if an add-on's current version supports an app."""
    addon = models.ForeignKey(Addon, on_delete=models.CASCADE)
    app = models.PositiveIntegerField(choices=amo.APPS_CHOICES,
                                      db_column='app_id')
    min = models.BigIntegerField("Minimum app version", null=True)
    max = models.BigIntegerField("Maximum app version", null=True)

    class Meta:
        db_table = 'appsupport'
        unique_together = ('addon', 'app')


class DeniedSlug(ModelBase):
    name = models.CharField(max_length=255, unique=True, default='')

    class Meta:
        db_table = 'addons_denied_slug'

    def __unicode__(self):
        return self.name

    @classmethod
    def blocked(cls, slug):
        return slug.isdigit() or cls.objects.filter(name=slug).exists()


class FrozenAddon(models.Model):
    """Add-ons in this table never get a hotness score."""
    addon = models.ForeignKey(Addon)

    class Meta:
        db_table = 'frozen_addons'

    def __unicode__(self):
        return 'Frozen: %s' % self.addon_id


@receiver(dbsignals.post_save, sender=FrozenAddon)
def freezer(sender, instance, **kw):
    # Adjust the hotness of the FrozenAddon.
    if instance.addon_id:
        Addon.objects.get(id=instance.addon_id).update(hotness=0)


class CompatOverride(ModelBase):
    """Helps manage compat info for add-ons not hosted on AMO."""
    name = models.CharField(max_length=255, blank=True, null=True)
    guid = models.CharField(max_length=255, unique=True)
    addon = models.ForeignKey(Addon, blank=True, null=True,
                              help_text='Fill this out to link an override '
                                        'to a hosted add-on')

    class Meta:
        db_table = 'compat_override'
        unique_together = ('addon', 'guid')

    def save(self, *args, **kw):
        if not self.addon:
            qs = Addon.objects.filter(guid=self.guid)
            if qs:
                self.addon = qs[0]
        return super(CompatOverride, self).save(*args, **kw)

    def __unicode__(self):
        if self.addon:
            return unicode(self.addon)
        elif self.name:
            return '%s (%s)' % (self.name, self.guid)
        else:
            return self.guid

    def is_hosted(self):
        """Am I talking about an add-on on AMO?"""
        return bool(self.addon_id)

    @staticmethod
    def transformer(overrides):
        if not overrides:
            return

        id_map = dict((o.id, o) for o in overrides)
        qs = CompatOverrideRange.objects.filter(compat__in=id_map)

        for compat_id, ranges in sorted_groupby(qs, 'compat_id'):
            id_map[compat_id].compat_ranges = list(ranges)

    # May be filled in by a transformer for performance.
    @cached_property
    def compat_ranges(self):
        return list(self._compat_ranges.all())

    def collapsed_ranges(self):
        """Collapse identical version ranges into one entity."""
        Range = collections.namedtuple('Range', 'type min max apps')
        AppRange = collections.namedtuple('AppRange', 'app min max')
        rv = []

        def sort_key(x):
            return (x.min_version, x.max_version, x.type)

        for key, compats in sorted_groupby(self.compat_ranges, key=sort_key):
            compats = list(compats)
            first = compats[0]
            item = Range(first.override_type(), first.min_version,
                         first.max_version, [])
            for compat in compats:
                app = AppRange(amo.APPS_ALL[compat.app],
                               compat.min_app_version, compat.max_app_version)
                item.apps.append(app)
            rv.append(item)
        return rv


OVERRIDE_TYPES = (
    (0, 'Compatible (not supported)'),
    (1, 'Incompatible'),
)


class CompatOverrideRange(ModelBase):
    """App compatibility for a certain version range of a RemoteAddon."""
    compat = models.ForeignKey(CompatOverride, related_name='_compat_ranges')
    type = models.SmallIntegerField(choices=OVERRIDE_TYPES, default=1)
    min_version = models.CharField(
        max_length=255, default='0',
        help_text=u'If not "0", version is required to exist for the override'
                  u' to take effect.')
    max_version = models.CharField(
        max_length=255, default='*',
        help_text=u'If not "*", version is required to exist for the override'
                  u' to take effect.')
    app = models.PositiveIntegerField(choices=amo.APPS_CHOICES,
                                      db_column='app_id')
    min_app_version = models.CharField(max_length=255, default='0')
    max_app_version = models.CharField(max_length=255, default='*')

    class Meta:
        db_table = 'compat_override_range'

    def override_type(self):
        """This is what Firefox wants to see in the XML output."""
        return {0: 'compatible', 1: 'incompatible'}[self.type]


class IncompatibleVersions(ModelBase):
    """
    Denormalized table to join against for fast compat override filtering.

    This was created to be able to join against a specific version record since
    the CompatOverrideRange can be wildcarded (e.g. 0 to *, or 1.0 to 1.*), and
    addon versioning isn't as consistent as Firefox versioning to trust
    `version_int` in all cases.  So extra logic needed to be provided for when
    a particular version falls within the range of a compatibility override.
    """
    version = models.ForeignKey(Version, related_name='+')
    app = models.PositiveIntegerField(choices=amo.APPS_CHOICES,
                                      db_column='app_id')
    min_app_version = models.CharField(max_length=255, blank=True, default='0')
    max_app_version = models.CharField(max_length=255, blank=True, default='*')
    min_app_version_int = models.BigIntegerField(blank=True, null=True,
                                                 editable=False, db_index=True)
    max_app_version_int = models.BigIntegerField(blank=True, null=True,
                                                 editable=False, db_index=True)

    class Meta:
        db_table = 'incompatible_versions'

    def __unicode__(self):
        return u'<IncompatibleVersion V:%s A:%s %s-%s>' % (
            self.version.id, self.app.id, self.min_app_version,
            self.max_app_version)

    def save(self, *args, **kw):
        self.min_app_version_int = version_int(self.min_app_version)
        self.max_app_version_int = version_int(self.max_app_version)
        return super(IncompatibleVersions, self).save(*args, **kw)


def update_incompatible_versions(sender, instance, **kw):
    if not instance.compat.addon_id:
        return
    if not instance.compat.addon.type == amo.ADDON_EXTENSION:
        return

    from . import tasks
    versions = instance.compat.addon.versions.values_list('id', flat=True)
    for chunk in chunked(versions, 50):
        tasks.update_incompatible_appversions.delay(chunk)


class ReplacementAddon(ModelBase):
    guid = models.CharField(max_length=255, unique=True, null=True)
    path = models.CharField(max_length=255, null=True,
                            help_text=_('Addon and collection paths need to '
                                        'end with "/"'))

    class Meta:
        db_table = 'replacement_addons'

    @staticmethod
    def path_is_external(path):
        return urlparse.urlsplit(path).scheme in ['http', 'https']

    def has_external_url(self):
        return self.path_is_external(self.path)


models.signals.post_save.connect(update_incompatible_versions,
                                 sender=CompatOverrideRange,
                                 dispatch_uid='cor_update_incompatible')
models.signals.post_delete.connect(update_incompatible_versions,
                                   sender=CompatOverrideRange,
                                   dispatch_uid='cor_update_incompatible')


def track_new_status(sender, instance, *args, **kw):
    if kw.get('raw'):
        # The addon is being loaded from a fixure.
        return
    if kw.get('created'):
        track_addon_status_change(instance)


models.signals.post_save.connect(track_new_status,
                                 sender=Addon,
                                 dispatch_uid='track_new_addon_status')


@Addon.on_change
def track_status_change(old_attr=None, new_attr=None, **kw):
    if old_attr is None:
        old_attr = {}
    if new_attr is None:
        new_attr = {}
    new_status = new_attr.get('status')
    old_status = old_attr.get('status')
    if new_status != old_status:
        track_addon_status_change(kw['instance'])


def track_addon_status_change(addon):
    statsd.incr('addon_status_change.all.status_{}'
                .format(addon.status))
