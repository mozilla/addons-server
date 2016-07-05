# -*- coding: utf-8 -*-
import collections
import itertools
import json
import os
import posixpath
import re
import time

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.core.files.storage import default_storage as storage
from django.db import models, transaction
from django.dispatch import receiver
from django.db.models import Max, Q, signals as dbsignals
from django.utils.translation import trans_real, ugettext_lazy as _

import caching.base as caching
import commonware.log
from django_extensions.db.fields.json import JSONField
from django_statsd.clients import statsd
from jinja2.filters import do_dictsort

from olympia import amo
from olympia.amo.models import (
    SlugField, OnChangeMixin, ModelBase, ManagerBase, manual_order)
from olympia.access import acl
from olympia.addons.utils import (
    get_creatured_ids, get_featured_ids, generate_addon_guid)
from olympia.amo import helpers
from olympia.amo.decorators import use_master, write
from olympia.amo.utils import (
    attach_trans_dict, cache_ns_key, chunked, JSONEncoder,
    no_translation, send_mail, slugify, sorted_groupby, timer, to_language,
    urlparams, find_language)
from olympia.amo.urlresolvers import get_outgoing_url, reverse
from olympia.files.models import File
from olympia.files.utils import (
    extract_translations, resolve_i18n_message, parse_addon)
from olympia.reviews.models import Review
from olympia.tags.models import Tag
from olympia.translations.fields import (
    LinkifiedField, PurifiedField, save_signal, TranslatedField, Translation)
from olympia.translations.query import order_by_translation
from olympia.users.models import UserForeignKey, UserProfile
from olympia.versions.compare import version_int
from olympia.versions.models import inherit_nomination, Version

from . import query, signals


log = commonware.log.getLogger('z.addons')


def clean_slug(instance, slug_field='slug'):
    """Cleans a model instance slug.

    This strives to be as generic as possible as it's used by Addons
    and Collections, and maybe more in the future.

    """
    slug = getattr(instance, slug_field, None) or instance.name

    if not slug:
        # Initialize the slug with what we have available: a name translation,
        # or the id of the instance, or in last resort the model name.
        translations = Translation.objects.filter(id=instance.name_id)
        if translations.exists():
            slug = translations[0]
        elif instance.id:
            slug = str(instance.id)
        else:
            slug = instance.__class__.__name__

    max_length = instance._meta.get_field_by_name(slug_field)[0].max_length
    slug = slugify(slug)[:max_length]

    if BlacklistedSlug.blocked(slug):
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
        # Leave space for 99 clashes.
        slug = slugify(slug)[:max_length - 2]

        # There is a clash, so find a suffix that will make this slug unique.
        lookup = {'%s__startswith' % slug_field: slug}
        clashes = qs.filter(**lookup)

        # Try numbers between 1 and the number of clashes + 1 (+ 1 because we
        # start the range at 1, not 0):
        # if we have two clashes "foo1" and "foo2", we need to try "foox"
        # for x between 1 and 3 to be absolutely sure to find an available one.
        for idx in range(1, len(clashes) + 2):
            new = ('%s%s' % (slug, idx))[:max_length]
            if new not in clashes:
                slug = new
                break
        else:
            # This could happen. The current implementation (using
            # ``[:max_length -3]``) only works for the first 100 clashes in the
            # worst case (if the slug is equal to or longuer than
            # ``max_length - 3`` chars).
            # After that, {verylongslug}-100 will be trimmed down to
            # {verylongslug}-10, which is already assigned, but it's the last
            # solution tested.
            raise RuntimeError

    setattr(instance, slug_field, slug)

    return instance


class AddonManager(ManagerBase):

    def __init__(self, include_deleted=False, include_unlisted=False):
        # DO NOT change the default value of include_deleted and
        # include_unlisted unless you've read through the comment just above
        # the Addon managers declaration/instanciation and understand the
        # consequences.
        ManagerBase.__init__(self)
        self.include_deleted = include_deleted
        self.include_unlisted = include_unlisted

    def get_queryset(self):
        qs = super(AddonManager, self).get_queryset()
        qs = qs._clone(klass=query.IndexQuerySet)
        if not self.include_deleted:
            qs = qs.exclude(status=amo.STATUS_DELETED)
        if not self.include_unlisted:
            qs = qs.exclude(is_listed=False)
        return qs.transform(Addon.transformer)

    def id_or_slug(self, val):
        if isinstance(val, basestring) and not val.isdigit():
            return self.filter(slug=val)
        return self.filter(id=val)

    def enabled(self):
        return self.filter(disabled_by_user=False)

    def public(self):
        """Get public add-ons only"""
        return self.filter(self.valid_q([amo.STATUS_PUBLIC]))

    def reviewed(self):
        """Get add-ons with a reviewed status"""
        return self.filter(self.valid_q(amo.REVIEWED_STATUSES))

    def unreviewed(self):
        """Get only unreviewed add-ons"""
        return self.filter(self.valid_q(amo.UNREVIEWED_STATUSES))

    def valid(self):
        """Get valid, enabled add-ons only"""
        return self.filter(self.valid_q(amo.LISTED_STATUSES))

    def valid_and_disabled_and_pending(self):
        """
        Get valid, pending, enabled and disabled add-ons.
        Used to allow pending theme pages to still be viewed.
        """
        statuses = list(amo.LISTED_STATUSES) + [amo.STATUS_DISABLED,
                                                amo.STATUS_PENDING]
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
        Listed add-ons have a version with a file matching ``status`` and are
        not disabled.  Personas and self-hosted add-ons will be returned too.
        """
        if len(status) == 0:
            status = [amo.STATUS_PUBLIC]
        return self.filter(self.valid_q(status), appsupport__app=app.id)

    def valid_q(self, status=[], prefix=''):
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


class Addon(OnChangeMixin, ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES_ADDON

    guid = models.CharField(max_length=255, unique=True, null=True)
    slug = models.CharField(max_length=30, unique=True, null=True)
    name = TranslatedField(default=None)
    default_locale = models.CharField(max_length=10,
                                      default=settings.LANGUAGE_CODE,
                                      db_column='defaultlocale')

    type = models.PositiveIntegerField(
        choices=amo.ADDON_TYPE.items(), db_column='addontype_id', default=0)
    status = models.PositiveIntegerField(
        choices=STATUS_CHOICES.items(), db_index=True, default=0)
    icon_type = models.CharField(max_length=25, blank=True,
                                 db_column='icontype')
    homepage = TranslatedField()
    support_email = TranslatedField(db_column='supportemail')
    support_url = TranslatedField(db_column='supporturl')
    description = PurifiedField(short=False)

    summary = LinkifiedField()
    developer_comments = PurifiedField(db_column='developercomments')
    eula = PurifiedField()
    privacy_policy = PurifiedField(db_column='privacypolicy')
    the_reason = PurifiedField()
    the_future = PurifiedField()

    average_rating = models.FloatField(max_length=255, default=0, null=True,
                                       db_column='averagerating')
    bayesian_rating = models.FloatField(default=0, db_index=True,
                                        db_column='bayesianrating')
    total_reviews = models.PositiveIntegerField(default=0,
                                                db_column='totalreviews')
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
    prerelease = models.BooleanField(default=False)
    admin_review = models.BooleanField(default=False, db_column='adminreview')
    site_specific = models.BooleanField(default=False,
                                        db_column='sitespecific')
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

    wants_contributions = models.BooleanField(default=False)
    paypal_id = models.CharField(max_length=255, blank=True)
    charity = models.ForeignKey('Charity', null=True)

    suggested_amount = models.DecimalField(
        max_digits=9, decimal_places=2, blank=True,
        null=True, help_text=_(u'Users have the option of contributing more '
                               'or less than this amount.'))

    total_contributions = models.DecimalField(max_digits=9, decimal_places=2,
                                              blank=True, null=True)

    annoying = models.PositiveIntegerField(
        choices=amo.CONTRIB_CHOICES, default=0,
        help_text=_(u'Users will always be asked in the Add-ons'
                    u' Manager (Firefox 4 and above).'
                    u' Only applies to desktop.'))
    enable_thankyou = models.BooleanField(
        default=False, help_text='Should the thank you note be sent to '
                                 'contributors?')
    thankyou_note = TranslatedField()

    authors = models.ManyToManyField('users.UserProfile', through='AddonUser',
                                     related_name='addons')
    categories = models.ManyToManyField('Category', through='AddonCategory')
    dependencies = models.ManyToManyField('self', symmetrical=False,
                                          through='AddonDependency',
                                          related_name='addons')

    _current_version = models.ForeignKey(Version, db_column='current_version',
                                         related_name='+', null=True,
                                         on_delete=models.SET_NULL)
    _latest_version = models.ForeignKey(Version, db_column='latest_version',
                                        on_delete=models.SET_NULL,
                                        null=True, related_name='+')
    whiteboard = models.TextField(blank=True)

    # Whether the add-on is listed on AMO or not.
    is_listed = models.BooleanField(default=True, db_index=True)

    # The order of those managers is very important:
    # The first one discovered, if it has "use_for_related_fields = True"
    # (which it has if it's inheriting from caching.base.CachingManager), will
    # be used for relations like `version.addon`. We thus want one that is NOT
    # filtered in any case, we don't want a 500 if the addon is not found
    # (because it has the status amo.STATUS_DELETED for example).
    # The CLASS of the first one discovered will also be used for "many to many
    # relations" like `collection.addons`. In that case, we do want the
    # filtered version by default, to make sure we're not displaying stuff by
    # mistake. You thus want the CLASS of the first one to be filtered by
    # default.
    # We don't control the instantiation, but AddonManager sets include_deleted
    # and include_unlisted to False by default, so filtering is enabled by
    # default. This is also why it's not repeated for 'objects' below.
    unfiltered = AddonManager(include_deleted=True, include_unlisted=True)
    with_unlisted = AddonManager(include_unlisted=True)
    objects = AddonManager()

    class Meta:
        db_table = 'addons'

    @staticmethod
    def __new__(cls, *args, **kw):
        try:
            type_idx = Addon._meta._type_idx
        except AttributeError:
            type_idx = (idx for idx, f in enumerate(Addon._meta.fields)
                        if f.attname == 'type').next()
            Addon._meta._type_idx = type_idx
        return object.__new__(cls)

    def __unicode__(self):
        return u'%s: %s' % (self.id, self.name)

    def __init__(self, *args, **kw):
        super(Addon, self).__init__(*args, **kw)
        self._first_category = {}

        if self.type == amo.ADDON_PERSONA:
            self.STATUS_CHOICES = Persona.STATUS_CHOICES

    def save(self, **kw):
        self.clean_slug()
        super(Addon, self).save(**kw)

    # Like the above Manager objects (`objects`, `with_unlisted`, ...), but
    # for ElasticSearch queries.
    @classmethod
    def search_public(cls):
        return cls.search_with_unlisted().filter(is_listed=True)

    @classmethod
    def search_with_unlisted(cls):
        return cls.search().filter(
            is_disabled=False, status__in=amo.REVIEWED_STATUSES)

    @use_master
    def clean_slug(self, slug_field='slug'):
        if self.status == amo.STATUS_DELETED:
            return
        clean_slug(self, slug_field)

    def is_soft_deleteable(self):
        return self.status or Version.unfiltered.filter(addon=self).exists()

    @transaction.atomic
    def delete(self, msg='', reason=''):
        # To avoid a circular import.
        from . import tasks
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

        if soft_deletion:
            # /!\ If we ever stop using soft deletion, and remove this code, we
            # need to make sure that the logs created below aren't cascade
            # deleted!

            log.debug('Deleting add-on: %s' % self.id)

            to = [settings.FLIGTAR]
            user = amo.get_user()

            # Don't localize email to admins, use 'en-US' always.
            with no_translation():
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
                'url': helpers.absolutify(self.get_url_path()),
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

            # Update or NULL out various fields.
            models.signals.pre_delete.send(sender=Addon, instance=self)
            self._reviews.all().delete()
            # The last parameter is needed to automagically create an AddonLog.
            amo.log(amo.LOG.DELETE_ADDON, self.pk, unicode(self.guid), self)
            self.update(status=amo.STATUS_DELETED, slug=None,
                        _current_version=None)
            models.signals.post_delete.send(sender=Addon, instance=self)

            send_mail(subject, email_msg, recipient_list=to)
        else:
            # Real deletion path.
            super(Addon, self).delete()

        for preview in previews:
            tasks.delete_preview_files.delay(preview)

        return True

    @classmethod
    def initialize_addon_from_upload(cls, data, upload, is_listed=True):
        fields = cls._meta.get_all_field_names()
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

        addon = Addon(**dict((k, v) for k, v in data.items() if k in fields))

        addon.status = amo.STATUS_NULL
        addon.is_listed = is_listed
        locale_is_set = (addon.default_locale and
                         addon.default_locale in (
                             settings.AMO_LANGUAGES +
                             settings.HIDDEN_LANGUAGES) and
                         data.get('default_locale') == addon.default_locale)
        if not locale_is_set:
            addon.default_locale = to_language(trans_real.get_language())

        addon.save()

        if old_guid_addon:
            old_guid_addon.update(guid='guid-reused-by-pk-{}'.format(addon.pk))
            old_guid_addon.save()
        return addon

    @classmethod
    def create_addon_from_upload_data(cls, data, upload, user=None, **kwargs):
        addon = cls.initialize_addon_from_upload(data, upload=upload, **kwargs)
        AddonUser(addon=addon, user=user).save()
        return addon

    @classmethod
    def from_upload(cls, upload, platforms, source=None, is_listed=True,
                    data=None):
        if not data:
            data = parse_addon(upload)

        addon = cls.initialize_addon_from_upload(
            is_listed=is_listed, data=data, upload=upload)

        if upload.validation_timeout:
            addon.update(admin_review=True)
        Version.from_upload(upload, addon, platforms, source=source)

        amo.log(amo.LOG.CREATE_ADDON, addon)
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
        if not self.is_listed:  # Not listed? Doesn't have a public page.
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

    def get_detail_url(self, action='detail', args=[]):
        return reverse('addons.%s' % action, args=[self.slug] + args)

    def meet_the_dev_url(self):
        return reverse('addons.meet', args=[self.slug])

    @property
    def reviews_url(self):
        return helpers.url('addons.reviews.list', self.slug)

    def get_ratings_url(self, action='list', args=None, add_prefix=True):
        return reverse('ratings.themes.%s' % action,
                       args=[self.slug] + (args or []),
                       add_prefix=add_prefix)

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

    @property
    def automated_signing(self):
        # We allow automated signing for add-ons which are not listed.
        # Beta versions are a special case for listed add-ons, and are dealt
        # with on a file-by-file basis.
        return not self.is_listed

    @property
    def is_sideload(self):
        # An add-on can side-load if it has been fully reviewed.
        return self.status in (amo.STATUS_NOMINATED, amo.STATUS_PUBLIC)

    @amo.cached_property(writable=True)
    def listed_authors(self):
        return UserProfile.objects.filter(
            addons=self,
            addonuser__listed=True).order_by('addonuser__position')

    @classmethod
    def get_fallback(cls):
        return cls._meta.get_field('default_locale')

    @property
    def reviews(self):
        return Review.objects.filter(addon=self, reply_to=None)

    def get_category(self, app):
        if app in getattr(self, '_first_category', {}):
            return self._first_category[app]
        categories = list(self.categories.filter(application=app))
        return categories[0] if categories else None

    def language_ascii(self):
        lang = trans_real.to_language(self.default_locale)
        return settings.LANGUAGES.get(lang)

    @property
    def valid_file_statuses(self):
        if self.status == amo.STATUS_PUBLIC:
            return [amo.STATUS_PUBLIC]

        if self.status in (amo.STATUS_LITE,
                           amo.STATUS_LITE_AND_NOMINATED):
            return [amo.STATUS_PUBLIC, amo.STATUS_LITE,
                    amo.STATUS_LITE_AND_NOMINATED]

        return amo.VALID_STATUSES

    def get_version(self):
        """Retrieve the latest public version of an addon."""
        if self.type == amo.ADDON_PERSONA:
            return
        try:
            status = self.valid_file_statuses

            status_list = ','.join(map(str, status))
            fltr = {'files__status__in': status}
            return self.versions.no_cache().filter(**fltr).extra(
                where=["""
                    NOT EXISTS (
                        SELECT 1 FROM files AS f2
                        WHERE f2.version_id = versions.id AND
                              f2.status NOT IN (%s))
                    """ % status_list])[0]

        except (IndexError, Version.DoesNotExist):
            return None

    @write
    def update_version(self, ignore=None, _signal=True):
        """
        Returns true if we updated the field.

        The optional ``ignore`` parameter, if present, is a a version
        to not consider as part of the update, since it may be in the
        process of being deleted.

        Pass ``_signal=False`` if you want to no signals fired at all.

        """
        if self.is_persona():
            # Versions are not as critical on themes.
            # If there are no versions, just create one and go.
            if not self._current_version:
                if self._latest_version:
                    self.update(_current_version=self._latest_version,
                                _signal=False)
                return True
            return False

        current = self.get_version()

        # We can't use .exclude(files__status=STATUS_DISABLED) because this
        # excludes a version if any of the files are the disabled and there may
        # be files we do want to include.  Having a single beta file /does/
        # mean we want the whole version disqualified though.
        statuses_without_disabled = (
            set(amo.STATUS_CHOICES_FILE.keys()) -
            {amo.STATUS_DISABLED, amo.STATUS_BETA})
        try:
            latest_qs = (
                self.versions.exclude(files__status=amo.STATUS_BETA).filter(
                    files__status__in=statuses_without_disabled))
            if ignore is not None:
                latest_qs = latest_qs.exclude(pk=ignore.pk)
            latest = latest_qs.latest()
        except Version.DoesNotExist:
            latest = None
        latest_id = latest and latest.id

        diff = [self._current_version, current]

        # Sometimes the DB is in an inconsistent state when this
        # signal is dispatched.
        try:
            if self._latest_version:
                # Make sure stringifying this does not trigger
                # Version.DoesNotExist before trying to use it for
                # logging.
                unicode(self._latest_version)
            diff += [self._latest_version, latest]
        except Version.DoesNotExist:
            diff += [self._latest_version_id, latest_id]

        updated = {}
        send_signal = False
        if self._current_version != current:
            updated.update({'_current_version': current})
            send_signal = True
        # Don't use self.latest_version here. It may throw Version.DoesNotExist
        # if we're called from a post_delete signal. We also don't set
        # send_signal since we only want this fired if the public version
        # changes.
        if self._latest_version_id != latest_id:
            updated.update({'_latest_version': latest})

        # update_version can be called by a post_delete signal (such
        # as File's) when deleting a version. If so, we should avoid putting
        # that version-being-deleted in any fields.
        if ignore is not None:
            updated = dict([(k, v) for (k, v) in updated.iteritems()
                            if v != ignore])

        if updated:
            # Pass along _signal to the .update() to prevent it from firing
            # signals if we don't want them.
            updated['_signal'] = _signal
            try:
                self.update(**updated)
                if send_signal and _signal:
                    signals.version_changed.send(sender=self)
                log.info(u'Version changed from current: %s to %s, '
                         u'latest: %s to %s for addon %s'
                         % tuple(diff + [self]))
            except Exception, e:
                log.error(u'Could not save version changes current: %s to %s, '
                          u'latest: %s to %s for addon %s (%s)' %
                          tuple(diff + [self, e]))

        return bool(updated)

    def compatible_version(self, app_id, app_version=None, platform=None,
                           compat_mode='strict'):
        """Returns the newest compatible version given the input."""
        if not app_id:
            return None

        if platform:
            # We include platform_id=1 always in the SQL so we skip it here.
            platform = platform.lower()
            if platform != 'all' and platform in amo.PLATFORM_DICT:
                platform = amo.PLATFORM_DICT[platform].id
            else:
                platform = None

        log.debug(u'Checking compatibility for add-on ID:%s, APP:%s, V:%s, '
                  u'OS:%s, Mode:%s' % (self.id, app_id, app_version, platform,
                                       compat_mode))
        valid_file_statuses = ','.join(map(str, self.valid_file_statuses))
        data = dict(id=self.id, app_id=app_id, platform=platform,
                    valid_file_statuses=valid_file_statuses)
        if app_version:
            data.update(version_int=version_int(app_version))
        else:
            # We can't perform the search queries for strict or normal without
            # an app version.
            compat_mode = 'ignore'

        ns_key = cache_ns_key('d2c-versions:%s' % self.id)
        cache_key = '%s:%s:%s:%s:%s' % (ns_key, app_id, app_version, platform,
                                        compat_mode)
        version_id = cache.get(cache_key)
        if version_id is not None:
            log.debug(u'Found compatible version in cache: %s => %s' % (
                      cache_key, version_id))
            if version_id == 0:
                return None
            else:
                try:
                    return Version.objects.get(pk=version_id)
                except Version.DoesNotExist:
                    pass

        raw_sql = ["""
            SELECT versions.*
            FROM versions
            INNER JOIN addons
                ON addons.id = versions.addon_id AND addons.id = %(id)s
            INNER JOIN applications_versions
                ON applications_versions.version_id = versions.id
            INNER JOIN appversions appmin
                ON appmin.id = applications_versions.min
                AND appmin.application_id = %(app_id)s
            INNER JOIN appversions appmax
                ON appmax.id = applications_versions.max
                AND appmax.application_id = %(app_id)s
            INNER JOIN files
                ON files.version_id = versions.id AND
                   (files.platform_id = 1"""]

        if platform:
            raw_sql.append(' OR files.platform_id = %(platform)s')

        raw_sql.append(') WHERE files.status IN (%(valid_file_statuses)s) ')

        if app_version:
            raw_sql.append('AND appmin.version_int <= %(version_int)s ')

        if compat_mode == 'ignore':
            pass  # No further SQL modification required.

        elif compat_mode == 'normal':
            raw_sql.append("""AND
                CASE WHEN files.strict_compatibility = 1 OR
                          files.binary_components = 1
                THEN appmax.version_int >= %(version_int)s ELSE 1 END
            """)
            # Filter out versions that don't have the minimum maxVersion
            # requirement to qualify for default-to-compatible.
            d2c_max = amo.D2C_MAX_VERSIONS.get(app_id)
            if d2c_max:
                data['d2c_max_version'] = version_int(d2c_max)
                raw_sql.append(
                    "AND appmax.version_int >= %(d2c_max_version)s ")

            # Filter out versions found in compat overrides
            raw_sql.append("""AND
                NOT versions.id IN (
                SELECT version_id FROM incompatible_versions
                WHERE app_id=%(app_id)s AND
                  (min_app_version='0' AND
                       max_app_version_int >= %(version_int)s) OR
                  (min_app_version_int <= %(version_int)s AND
                       max_app_version='*') OR
                  (min_app_version_int <= %(version_int)s AND
                       max_app_version_int >= %(version_int)s)) """)

        else:  # Not defined or 'strict'.
            raw_sql.append('AND appmax.version_int >= %(version_int)s ')

        raw_sql.append('ORDER BY versions.id DESC LIMIT 1;')

        version = Version.objects.raw(''.join(raw_sql) % data)
        if version:
            version = version[0]
            version_id = version.id
        else:
            version = None
            version_id = 0

        log.debug(u'Caching compat version %s => %s' % (cache_key, version_id))
        cache.set(cache_key, version_id, None)

        return version

    def increment_version(self):
        """Increment version number by 1."""
        version = self.latest_version or self.current_version
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
        """Returns the current_version or None if the app is deleted or not
        created yet"""
        if not self.id or self.status == amo.STATUS_DELETED:
            return None
        try:
            return self._current_version
        except ObjectDoesNotExist:
            pass
        return None

    @property
    def latest_version(self):
        """Returns the latest_version or None if the app is deleted or not
        created yet"""
        if not self.id or self.status == amo.STATUS_DELETED:
            return None
        try:
            return self._latest_version
        except ObjectDoesNotExist:
            pass
        return None

    @amo.cached_property
    def binary(self):
        """Returns if the current version has binary files."""
        version = self.current_version
        if version:
            return version.files.filter(binary=True).exists()
        return False

    @amo.cached_property
    def binary_components(self):
        """Returns if the current version has files with binary_components."""
        version = self.current_version
        if version:
            return version.files.filter(binary_components=True).exists()
        return False

    def get_icon_dir(self):
        return os.path.join(helpers.user_media_path('addon_icons'),
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
            modified = int(time.mktime(self.modified.timetuple()))
            path = '/'.join([
                split_id.group(2) or '0',
                '{0}-{1}.png?modified={2}'.format(self.id, size, modified),
            ])
            return helpers.user_media_url('addon_icons') + path

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

        def logit(reason, old=self.status):
            log.info('Changing add-on status [%s]: %s => %s (%s).'
                     % (self.id, old, self.status, reason))
            amo.log(amo.LOG.CHANGE_STATUS, self.get_status_display(), self)

        versions = self.versions.all()
        status = None
        if not versions.exists():
            status = amo.STATUS_NULL
            logit('no versions')
        elif not versions.filter(
                files__status__in=amo.VALID_STATUSES).exists():
            status = amo.STATUS_NULL
            logit('no version with valid file')
        elif (self.status == amo.STATUS_PUBLIC and
              not versions.filter(files__status=amo.STATUS_PUBLIC).exists()):
            if versions.filter(files__status=amo.STATUS_LITE).exists():
                status = amo.STATUS_LITE
                logit('only lite files')
            else:
                status = amo.STATUS_UNREVIEWED
                logit('no reviewed files')
        elif (self.status in amo.REVIEWED_STATUSES and
              self.latest_version and
              self.latest_version.has_files and
              (self.latest_version.all_files[0].status
                in amo.UNDER_REVIEW_STATUSES)):
            # Addon is public, but its latest file is not (it's the case on a
            # new file upload). So, call update, to trigger watch_status, which
            # takes care of setting nomination time when needed.
            status = self.status

        if status is not None:
            self.update(status=status)

        self.update_version(ignore=ignore_version)

    @staticmethod
    def attach_related_versions(addons, addon_dict=None):
        if addon_dict is None:
            addon_dict = dict((a.id, a) for a in addons)

        current_ids = filter(None, (a._current_version_id for a in addons))
        latest_ids = filter(None, (a._latest_version_id for a in addons))
        all_ids = set(current_ids) | set(latest_ids)

        versions = list(Version.objects.filter(id__in=all_ids).order_by())
        for version in versions:
            try:
                addon = addon_dict[version.addon_id]
            except KeyError:
                log.debug('Version %s has an invalid add-on id.' % version.id)
                continue
            if addon._current_version_id == version.id:
                addon._current_version = version
            if addon._latest_version_id == version.id:
                addon._latest_version = version

            version.addon = addon

    @staticmethod
    def attach_listed_authors(addons, addon_dict=None):
        if addon_dict is None:
            addon_dict = dict((a.id, a) for a in addons)

        q = (UserProfile.objects.no_cache()
             .filter(addons__in=addons, addonuser__listed=True)
             .extra(select={'addon_id': 'addons_users.addon_id',
                            'position': 'addons_users.position'}))
        q = sorted(q, key=lambda u: (u.addon_id, u.position))
        for addon_id, users in itertools.groupby(q, key=lambda u: u.addon_id):
            addon_dict[addon_id].listed_authors = list(users)
        # FIXME: set listed_authors to empty list on addons without listed
        # authors.

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
    @timer
    def transformer(addons):
        if not addons:
            return

        addon_dict = dict((a.id, a) for a in addons)
        personas = [a for a in addons if a.type == amo.ADDON_PERSONA]
        addons = [a for a in addons if a.type != amo.ADDON_PERSONA]

        # Set _latest_version, _current_version
        Addon.attach_related_versions(addons, addon_dict=addon_dict)

        # Attach listed authors.
        Addon.attach_listed_authors(addons, addon_dict=addon_dict)

        for persona in Persona.objects.no_cache().filter(addon__in=personas):
            addon = addon_dict[persona.addon_id]
            addon.persona = persona
            addon.weekly_downloads = persona.popularity

        # Personas need categories for the JSON dump.
        Category.transformer(personas)

        # Attach previews.
        Addon.attach_previews(addons, addon_dict=addon_dict)

        # Attach _first_category for Firefox.
        cats = dict(AddonCategory.objects.values_list('addon', 'category')
                    .filter(addon__in=addon_dict,
                            category__application=amo.FIREFOX.id))
        qs = Category.objects.filter(id__in=set(cats.values()))
        categories = dict((c.id, c) for c in qs)
        for addon in addons:
            category = categories[cats[addon.id]] if addon.id in cats else None
            addon._first_category[amo.FIREFOX.id] = category

        return addon_dict

    @property
    def show_beta(self):
        return self.status == amo.STATUS_PUBLIC and self.current_beta_version

    def show_adu(self):
        return self.type != amo.ADDON_SEARCH

    @amo.cached_property
    def current_beta_version(self):
        """Retrieves the latest version of an addon, in the beta channel."""
        versions = self.versions.filter(files__status=amo.STATUS_BETA)[:1]

        if versions:
            return versions[0]

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
        """Return the statuses an add-on can request."""
        if not File.objects.filter(version__addon=self):
            return ()
        if (self.is_disabled or
                self.status in (amo.STATUS_PUBLIC,
                                amo.STATUS_LITE_AND_NOMINATED,
                                amo.STATUS_DELETED) or
                not self.latest_version or
                not self.latest_version.files.exclude(
                    status=amo.STATUS_DISABLED)):
            return ()
        elif self.status == amo.STATUS_NOMINATED:
            return (amo.STATUS_LITE,)
        elif self.status in [amo.STATUS_UNREVIEWED, amo.STATUS_LITE]:
            return (amo.STATUS_PUBLIC,)
        else:
            return (amo.STATUS_LITE, amo.STATUS_PUBLIC)

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

    @property
    def is_under_review(self):
        return self.status in amo.UNDER_REVIEW_STATUSES

    def is_unreviewed(self):
        return self.status in amo.UNREVIEWED_STATUSES

    def is_public(self):
        return self.status == amo.STATUS_PUBLIC and not self.disabled_by_user

    def is_incomplete(self):
        from olympia.devhub.models import SubmitStep  # Avoid import loop.
        return SubmitStep.objects.filter(addon=self).exists()

    def is_pending(self):
        return self.status == amo.STATUS_PENDING

    def is_rejected(self):
        return self.status == amo.STATUS_REJECTED

    def is_reviewed(self):
        return self.status in amo.REVIEWED_STATUSES

    def can_be_deleted(self):
        return not self.is_deleted

    @classmethod
    def featured_random(cls, app, lang):
        return get_featured_ids(app, lang)

    def is_no_restart(self):
        """Is this a no-restart add-on?"""
        files = self.current_version and self.current_version.all_files
        return bool(files and files[0].no_restart)

    def is_featured(self, app, lang=None):
        """Is add-on globally featured for this app and language?"""
        if app:
            return self.id in get_featured_ids(app, lang)

    def has_full_profile(self):
        """Is developer profile public (completed)?"""
        return self.the_reason and self.the_future

    def has_profile(self):
        """Is developer profile (partially or entirely) completed?"""
        return self.the_reason or self.the_future

    @amo.cached_property
    def tags_partitioned_by_developer(self):
        """Returns a tuple of developer tags and user tags for this addon."""
        tags = self.tags.not_blacklisted()
        if self.is_persona:
            return [], tags
        user_tags = tags.exclude(addon_tags__user__in=self.listed_authors)
        dev_tags = tags.exclude(id__in=[t.id for t in user_tags])
        return dev_tags, user_tags

    @amo.cached_property(writable=True)
    def compatible_apps(self):
        """Shortcut to get compatible apps for the current version."""
        # Search providers and personas don't list their supported apps.
        if self.type in amo.NO_COMPAT:
            return dict((app, None) for app in
                        amo.APP_TYPE_SUPPORT[self.type])
        if self.current_version:
            return self.current_version.compatible_apps
        else:
            return {}

    def accepts_compatible_apps(self):
        """True if this add-on lists compatible apps."""
        return self.type not in amo.NO_COMPAT

    def incompatible_latest_apps(self):
        """Returns a list of applications with which this add-on is
        incompatible (based on the latest version).

        """
        return [a for a, v in self.compatible_apps.items() if v and
                version_int(v.max.version) < version_int(a.latest_version)]

    def has_author(self, user, roles=None):
        """True if ``user`` is an author with any of the specified ``roles``.

        ``roles`` should be a list of valid roles (see amo.AUTHOR_ROLE_*). If
        not specified, has_author will return true if the user has any role.
        """
        if user is None or user.is_anonymous():
            return False
        if roles is None:
            roles = dict(amo.AUTHOR_CHOICES).keys()
        return AddonUser.objects.filter(addon=self, user=user,
                                        role__in=roles).exists()

    @property
    def takes_contributions(self):
        return (self.status == amo.STATUS_PUBLIC and
                self.wants_contributions and
                (self.paypal_id or self.charity_id))

    @property
    def has_eula(self):
        return self.eula

    @classmethod
    def _last_updated_queries(cls):
        """
        Get the queries used to calculate addon.last_updated.
        """
        status_change = Max('versions__files__datestatuschanged')
        public = (
            Addon.objects.no_cache().filter(
                status=amo.STATUS_PUBLIC,
                versions__files__status=amo.STATUS_PUBLIC)
            .exclude(type=amo.ADDON_PERSONA)
            .values('id').annotate(last_updated=status_change))

        lite = (Addon.objects.no_cache()
                .filter(status__in=amo.LISTED_STATUSES,
                        versions__files__status=amo.STATUS_LITE)
                .values('id').annotate(last_updated=status_change))

        stati = amo.LISTED_STATUSES + (amo.STATUS_PUBLIC,)
        exp = (Addon.objects.no_cache().exclude(status__in=stati)
               .filter(versions__files__status__in=amo.VALID_STATUSES)
               .values('id')
               .annotate(last_updated=Max('versions__files__created')))

        personas = (Addon.objects.no_cache().filter(type=amo.ADDON_PERSONA)
                    .extra(select={'last_updated': 'created'}))
        return dict(public=public, exp=exp, personas=personas,
                    lite=lite)

    @amo.cached_property(writable=True)
    def all_categories(self):
        return list(self.categories.all())

    @amo.cached_property(writable=True)
    def all_previews(self):
        return list(self.get_previews())

    def get_previews(self):
        """Exclude promo graphics."""
        return self.previews.exclude(position=-1)

    @property
    def app_categories(self):
        categories = sorted_groupby(order_by_translation(self.categories.all(),
                                                         'name'),
                                    key=lambda x: x.application)
        app_cats = []
        for app_id, cats in categories:
            app = amo.APP_IDS.get(app_id)
            if app_id and not app:
                # Skip retired applications like Sunbird.
                continue
            app_cats.append((app, list(cats)))
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
        return not(user and self.has_author(user))

    @property
    def all_dependencies(self):
        """Return all the (valid) add-ons this add-on depends on."""
        return list(self.dependencies.valid().all()[:3])

    def has_installed(self, user):
        if not user or not isinstance(user, UserProfile):
            return False

        return self.installed.filter(user=user).exists()

    def get_latest_file(self):
        """Get the latest file from the current version."""
        cur = self.current_version
        if cur:
            res = cur.files.order_by('-created')
            if res:
                return res[0]

    def in_escalation_queue(self):
        return self.escalationqueue_set.exists()

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
                                         viewer=(not require_owner),
                                         ignore_disabled=ignore_disabled)

    @property
    def feature_compatibility(self):
        try:
            feature_compatibility = self.addonfeaturecompatibility
        except AddonFeatureCompatibility.DoesNotExist:
            # If it does not exist, return a blank one, no need to create. It's
            # the caller responsability to create when needed to avoid
            # unexpected database writes.
            feature_compatibility = AddonFeatureCompatibility()
        return feature_compatibility


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
def watch_status(old_attr={}, new_attr={}, instance=None,
                 sender=None, **kw):
    """
    Set nomination date if the addon is new in queue or updating.

    The nomination date cannot be reset, say, when a developer cancels
    their request for full review and re-requests full review.

    If a version is rejected after nomination, the developer has
    to upload a new version.

    """
    new_status = new_attr.get('status')
    old_status = old_attr.get('status')
    if (new_status not in amo.UNDER_REVIEW_STATUSES + amo.REVIEWED_STATUSES or
            not new_status or not instance.latest_version):
        return

    if old_status not in amo.UNDER_REVIEW_STATUSES:
        # New: will (re)set nomination only if it's None.
        instance.latest_version.reset_nomination_time()
    elif instance.latest_version.has_files:
        # Updating: inherit nomination from last nominated version.
        # Calls `inherit_nomination` manually given that signals are
        # deactivated to avoid circular calls.
        inherit_nomination(None, instance.latest_version)


@Addon.on_change
def watch_disabled(old_attr={}, new_attr={}, instance=None, sender=None, **kw):
    attrs = dict((k, v) for k, v in old_attr.items()
                 if k in ('disabled_by_user', 'status'))
    if Addon(**attrs).is_disabled and not instance.is_disabled:
        for f in File.objects.filter(version__addon=instance.id):
            f.unhide_disabled_file()
    if instance.is_disabled and not Addon(**attrs).is_disabled:
        for f in File.objects.filter(version__addon=instance.id):
            f.hide_disabled_file()


@Addon.on_change
def watch_developer_notes(old_attr={}, new_attr={}, instance=None, sender=None,
                          **kw):
    whiteboard_changed = (
        new_attr.get('whiteboard') and
        old_attr.get('whiteboard') != new_attr.get('whiteboard'))
    developer_comments_changed = (new_attr.get('_developer_comments_cache') and
                                  old_attr.get('_developer_comments_cache') !=
                                  new_attr.get('_developer_comments_cache'))
    if whiteboard_changed or developer_comments_changed:
        instance.versions.update(has_info_request=False)


def attach_categories(addons):
    """Put all of the add-on's categories into a category_ids list."""
    addon_dict = dict((a.id, a) for a in addons)
    categories = (Category.objects.filter(addoncategory__addon__in=addon_dict)
                  .values_list('addoncategory__addon', 'id'))
    for addon, cats in sorted_groupby(categories, lambda x: x[0]):
        addon_dict[addon].category_ids = [c[1] for c in cats]


def attach_translations(addons):
    """Put all translations into a translations dict."""
    attach_trans_dict(Addon, addons)


def attach_tags(addons):
    addon_dict = dict((a.id, a) for a in addons)
    qs = (Tag.objects.not_blacklisted().filter(addons__in=addon_dict)
          .values_list('addons__id', 'tag_text'))
    for addon, tags in sorted_groupby(qs, lambda x: x[0]):
        addon_dict[addon].tag_list = [t[1] for t in tags]


class Persona(caching.CachingMixin, models.Model):
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

    objects = caching.CachingManager()

    class Meta:
        db_table = 'personas'

    def __unicode__(self):
        return unicode(self.addon.name)

    def is_new(self):
        return self.persona_id == 0

    def _image_url(self, filename):
        return self.get_mirror_url(filename)

    def _image_path(self, filename):
        return os.path.join(helpers.user_media_path('addons'),
                            str(self.addon.id), filename)

    def get_mirror_url(self, filename):
        host = (settings.PRIVATE_MIRROR_URL if self.addon.is_disabled
                else helpers.user_media_url('addons'))
        image_url = posixpath.join(host, str(self.addon.id), filename or '')
        # TODO: Bust the cache on the hash of the image contents or something.
        if self.addon.modified is not None:
            modified = int(time.mktime(self.addon.modified.timetuple()))
        else:
            modified = 0
        return '%s?%s' % (image_url, modified)

    @amo.cached_property
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

    @amo.cached_property
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

    @amo.cached_property
    def icon_url(self):
        """URL to personas square preview."""
        if self.is_new():
            return self._image_url('icon.png')
        else:
            return self._image_url('preview_small.jpg')

    @amo.cached_property
    def icon_path(self):
        """Path to personas square preview."""
        if self.is_new():
            return self._image_path('icon.png')
        else:
            return self._image_path('preview_small.jpg')

    @amo.cached_property
    def preview_url(self):
        """URL to Persona's big, 680px, preview."""
        if self.is_new():
            return self._image_url('preview.png')
        else:
            return self._image_url('preview_large.jpg')

    @amo.cached_property
    def preview_path(self):
        """Path to Persona's big, 680px, preview."""
        if self.is_new():
            return self._image_path('preview.png')
        else:
            return self._image_path('preview_large.jpg')

    @amo.cached_property
    def header_url(self):
        return self._image_url(self.header)

    @amo.cached_property
    def footer_url(self):
        return self.footer and self._image_url(self.footer) or ''

    @amo.cached_property
    def header_path(self):
        return self._image_path(self.header)

    @amo.cached_property
    def footer_path(self):
        return self.footer and self._image_path(self.footer) or ''

    @amo.cached_property
    def update_url(self):
        locale = settings.LANGUAGE_URL_MAP.get(trans_real.get_language())
        return settings.NEW_PERSONAS_UPDATE_URL % {
            'locale': locale or settings.LANGUAGE_CODE,
            'id': self.addon.id
        }

    @amo.cached_property
    def theme_data(self):
        """Theme JSON Data for Browser/extension preview."""
        def hexcolor(color):
            return '#%s' % color

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
            'description': unicode(addon.description),
            'header': self.header_url,
            'footer': self.footer_url or '',
            'headerURL': self.header_url,
            'footerURL': self.footer_url or '',
            'previewURL': self.preview_url,
            'iconURL': self.icon_url,
            'updateURL': self.update_url,
            'detailURL': helpers.absolutify(self.addon.get_url_path()),
            'version': '1.0'
        }

    @property
    def json_data(self):
        """Persona JSON Data for Browser/extension preview."""
        return json.dumps(self.theme_data,
                          separators=(',', ':'), cls=JSONEncoder)

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

    @amo.cached_property(writable=True)
    def listed_authors(self):
        return self.addon.listed_authors


class AddonCategory(caching.CachingMixin, models.Model):
    addon = models.ForeignKey(Addon)
    category = models.ForeignKey('Category')
    feature = models.BooleanField(default=False)
    feature_locales = models.CharField(max_length=255, default='', null=True)

    objects = caching.CachingManager()

    class Meta:
        db_table = 'addons_categories'
        unique_together = ('addon', 'category')

    @classmethod
    def creatured_random(cls, category, lang):
        return get_creatured_ids(category, lang)


class AddonUser(caching.CachingMixin, models.Model):
    addon = models.ForeignKey(Addon)
    user = UserForeignKey()
    role = models.SmallIntegerField(default=amo.AUTHOR_ROLE_OWNER,
                                    choices=amo.AUTHOR_CHOICES)
    listed = models.BooleanField(_(u'Listed'), default=True)
    position = models.IntegerField(default=0)

    objects = caching.CachingManager()

    def __init__(self, *args, **kwargs):
        super(AddonUser, self).__init__(*args, **kwargs)
        self._original_role = self.role
        self._original_user_id = self.user_id

    class Meta:
        db_table = 'addons_users'


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


class BlacklistedGuid(ModelBase):
    guid = models.CharField(max_length=255, unique=True)
    comments = models.TextField(default='', blank=True)

    class Meta:
        db_table = 'blacklisted_guids'

    def __unicode__(self):
        return self.guid


class Category(OnChangeMixin, ModelBase):
    name = TranslatedField()
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

    def __unicode__(self):
        return unicode(self.name)

    def get_url_path(self):
        try:
            type = amo.ADDON_SLUGS[self.type]
        except KeyError:
            type = amo.ADDON_SLUGS[amo.ADDON_EXTENSION]
        return reverse('browse.%s' % type, args=[self.slug])

    @staticmethod
    def transformer(addons):
        qs = (Category.objects.no_cache().filter(addons__in=addons)
              .extra(select={'addon_id': 'addons_categories.addon_id'}))
        cats = dict((addon_id, list(cs))
                    for addon_id, cs in sorted_groupby(qs, 'addon_id'))
        for addon in addons:
            addon.all_categories = cats.get(addon.id, [])

    def clean(self):
        if self.slug.isdigit():
            raise ValidationError('Slugs cannot be all numbers.')


dbsignals.pre_save.connect(save_signal, sender=Category,
                           dispatch_uid='category_translations')


class Preview(ModelBase):
    addon = models.ForeignKey(Addon, related_name='previews')
    filetype = models.CharField(max_length=25)
    thumbtype = models.CharField(max_length=25)
    caption = TranslatedField()

    position = models.IntegerField(default=0)
    sizes = JSONField(max_length=25, default={})

    class Meta:
        db_table = 'previews'
        ordering = ('position', 'created')

    def _image_url(self, url_template):
        if self.modified is not None:
            modified = int(time.mktime(self.modified.timetuple()))
        else:
            modified = 0
        args = [self.id / 1000, self.id, modified]
        if '.png' not in url_template:
            args.insert(2, self.file_extension)
        return url_template % tuple(args)

    def _image_path(self, url_template):
        args = [self.id / 1000, self.id]
        if '.png' not in url_template:
            args.append(self.file_extension)
        return url_template % tuple(args)

    def as_dict(self, src=None):
        d = {'full': urlparams(self.image_url, src=src),
             'thumbnail': urlparams(self.thumbnail_url, src=src),
             'caption': unicode(self.caption)}
        return d

    @property
    def is_landscape(self):
        size = self.image_size
        if not size:
            return False
        return size[0] > size[1]

    @property
    def file_extension(self):
        # Assume that blank is an image.
        if not self.filetype:
            return 'png'
        return self.filetype.split('/')[1]

    @property
    def thumbnail_url(self):
        template = (
            helpers.user_media_url('previews') +
            'thumbs/%s/%d.png?modified=%s')
        return self._image_url(template)

    @property
    def image_url(self):
        template = (
            helpers.user_media_url('previews') +
            'full/%s/%d.%s?modified=%s')
        return self._image_url(template)

    @property
    def thumbnail_path(self):
        template = os.path.join(
            helpers.user_media_path('previews'),
            'thumbs',
            '%s',
            '%d.png'
        )
        return self._image_path(template)

    @property
    def image_path(self):
        template = os.path.join(
            helpers.user_media_path('previews'),
            'full',
            '%s',
            '%d.%s'
        )
        return self._image_path(template)

    @property
    def thumbnail_size(self):
        return self.sizes.get('thumbnail', []) if self.sizes else []

    @property
    def image_size(self):
        return self.sizes.get('image', []) if self.sizes else []

dbsignals.pre_save.connect(save_signal, sender=Preview,
                           dispatch_uid='preview_translations')


def delete_preview_files(sender, instance, **kw):
    """On delete of the Preview object from the database, unlink the image
    and thumb on the file system """
    for filename in [instance.image_path, instance.thumbnail_path]:
        if storage.exists(filename):
            log.info('Removing filename: %s for preview: %s'
                     % (filename, instance.pk))
            storage.delete(filename)


models.signals.post_delete.connect(delete_preview_files,
                                   sender=Preview,
                                   dispatch_uid='delete_preview_files')


class AppSupport(ModelBase):
    """Cache to tell us if an add-on's current version supports an app."""
    addon = models.ForeignKey(Addon)
    app = models.PositiveIntegerField(choices=amo.APPS_CHOICES,
                                      db_column='app_id')
    min = models.BigIntegerField("Minimum app version", null=True)
    max = models.BigIntegerField("Maximum app version", null=True)

    class Meta:
        db_table = 'appsupport'
        unique_together = ('addon', 'app')


class Charity(ModelBase):
    name = models.CharField(max_length=255)
    url = models.URLField()
    paypal = models.CharField(max_length=255)

    class Meta:
        db_table = 'charities'

    @property
    def outgoing_url(self):
        if self.pk == amo.FOUNDATION_ORG:
            return self.url
        return get_outgoing_url(unicode(self.url))


class BlacklistedSlug(ModelBase):
    name = models.CharField(max_length=255, unique=True, default='')

    class Meta:
        db_table = 'addons_blacklistedslug'

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
    @amo.cached_property(writable=True)
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
def track_status_change(old_attr={}, new_attr={}, **kw):
    new_status = new_attr.get('status')
    old_status = old_attr.get('status')
    if new_status != old_status:
        track_addon_status_change(kw['instance'])


def track_addon_status_change(addon):
    statsd.incr('addon_status_change.all.status_{}'
                .format(addon.status))

    listed_tag = 'listed' if addon.is_listed else 'unlisted'
    statsd.incr('addon_status_change.{}.status_{}'
                .format(listed_tag, addon.status))
