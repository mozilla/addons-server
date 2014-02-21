# -*- coding: utf-8 -*-
import collections
import itertools
import json
import os
import posixpath
import re
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models, transaction
from django.dispatch import receiver
from django.db.models import Max, Q, signals as dbsignals
from django.utils.translation import trans_real as translation

import caching.base as caching
import commonware.log
import json_field
import waffle
from jinja2.filters import do_dictsort
from tower import ugettext_lazy as _

from addons.utils import get_creatured_ids, get_featured_ids

import amo
import amo.models
from access import acl
from amo.decorators import use_master, write
from amo.fields import DecimalCharField
from amo.helpers import absolutify, shared_url
from amo.utils import (attach_trans_dict, cache_ns_key, chunked, find_language,
                       JSONEncoder, send_mail, slugify, sorted_groupby, timer,
                       to_language, urlparams)
from amo.urlresolvers import get_outgoing_url, reverse
from files.models import File
from reviews.models import Review
import sharing.utils as sharing
from stats.models import AddonShareCountTotal
from tags.models import Tag
from translations.fields import (LinkifiedField, PurifiedField, save_signal,
                                 TranslatedField, Translation)
from translations.query import order_by_translation
from users.models import UserForeignKey, UserProfile
from versions.compare import version_int
from versions.models import Version

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
        # Leave space for "-" and 99 clashes.
        slug = slugify(slug)[:max_length - 3]

        # There is a clash, so find a suffix that will make this slug unique.
        prefix = '%s-' % slug
        lookup = {'%s__startswith' % slug_field: prefix}
        clashes = qs.filter(**lookup)

        # Try numbers between 1 and the number of clashes + 1 (+ 1 because we
        # start the range at 1, not 0):
        # if we have two clashes "foo-1" and "foo-2", we need to try "foo-x"
        # for x between 1 and 3 to be absolutely sure to find an available one.
        for idx in range(1, len(clashes) + 2):
            new = ('%s%s' % (prefix, idx))[:max_length]
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


class AddonManager(amo.models.ManagerBase):

    def __init__(self, include_deleted=False):
        amo.models.ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_query_set(self):
        qs = super(AddonManager, self).get_query_set()
        qs = qs._clone(klass=query.IndexQuerySet)
        if not self.include_deleted:
            qs = qs.exclude(status=amo.STATUS_DELETED)
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
        return amo.models.manual_order(self.listed(app), ids, 'addons.id')

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


class Addon(amo.models.OnChangeMixin, amo.models.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()
    LOCALES = [(translation.to_locale(k).replace('_', '-'), v) for k, v in
               do_dictsort(settings.LANGUAGES)]

    guid = models.CharField(max_length=255, unique=True, null=True)
    slug = models.CharField(max_length=30, unique=True, null=True)
    # This column is only used for webapps, so they can have a slug namespace
    # separate from addons and personas.
    app_slug = models.CharField(max_length=30, unique=True, null=True,
                                blank=True)
    name = TranslatedField(default=None)
    default_locale = models.CharField(max_length=10,
                                      default=settings.LANGUAGE_CODE,
                                      db_column='defaultlocale')

    type = models.PositiveIntegerField(db_column='addontype_id', default=0)
    status = models.PositiveIntegerField(
        choices=STATUS_CHOICES, db_index=True, default=0)
    highest_status = models.PositiveIntegerField(
        choices=STATUS_CHOICES, default=0,
        help_text="An upper limit for what an author can change.",
        db_column='higheststatus')
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
    share_count = models.PositiveIntegerField(default=0, db_index=True,
                                              db_column='sharecount')
    last_updated = models.DateTimeField(
        db_index=True, null=True,
        help_text='Last time this add-on had a file/version update')
    ts_slowness = models.FloatField(
        db_index=True, null=True,
        help_text='How much slower this add-on makes browser ts tests. '
                  'Read as {addon.ts_slowness}% slower.')

    disabled_by_user = models.BooleanField(default=False, db_index=True,
                                           db_column='inactive')
    trusted = models.BooleanField(default=False)
    view_source = models.BooleanField(default=True, db_column='viewsource')
    public_stats = models.BooleanField(default=False, db_column='publicstats')
    prerelease = models.BooleanField(default=False)
    admin_review = models.BooleanField(default=False, db_column='adminreview')
    admin_review_type = models.PositiveIntegerField(
        choices=amo.ADMIN_REVIEW_TYPES.items(), default=amo.ADMIN_REVIEW_FULL)
    site_specific = models.BooleanField(default=False,
                                        db_column='sitespecific')
    external_software = models.BooleanField(default=False,
                                            db_column='externalsoftware')
    dev_agreement = models.BooleanField(
        default=False, help_text="Has the dev agreement been signed?")
    auto_repackage = models.BooleanField(
        default=True, help_text='Automatically upgrade jetpack add-on to a '
                                'new sdk version?')
    outstanding = models.BooleanField(default=False)

    nomination_message = models.TextField(null=True,
                                          db_column='nominationmessage')
    target_locale = models.CharField(
        max_length=255, db_index=True, blank=True, null=True,
        help_text="For dictionaries and language packs")
    locale_disambiguation = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="For dictionaries and language packs")

    wants_contributions = models.BooleanField(default=False)
    paypal_id = models.CharField(max_length=255, blank=True)
    charity = models.ForeignKey('Charity', null=True)
    # TODO(jbalogh): remove nullify_invalid once remora dies.
    suggested_amount = DecimalCharField(
        max_digits=8, decimal_places=2, nullify_invalid=True, blank=True,
        null=True, help_text=_(u'Users have the option of contributing more '
                               'or less than this amount.'))

    total_contributions = DecimalCharField(max_digits=8, decimal_places=2,
                                           nullify_invalid=True, blank=True,
                                           null=True)

    annoying = models.PositiveIntegerField(
        choices=amo.CONTRIB_CHOICES, default=0,
        help_text=_(u'Users will always be asked in the Add-ons'
                     ' Manager (Firefox 4 and above)'))
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
    premium_type = models.PositiveIntegerField(
        choices=amo.ADDON_PREMIUM_TYPES.items(), default=amo.ADDON_FREE)
    manifest_url = models.URLField(max_length=255, blank=True, null=True)
    app_domain = models.CharField(max_length=255, blank=True, null=True,
                                  db_index=True)

    _current_version = models.ForeignKey(Version, db_column='current_version',
                                         related_name='+', null=True,
                                         on_delete=models.SET_NULL)
    # This is for Firefox only.
    _backup_version = models.ForeignKey(
        Version, related_name='___backup', db_column='backup_version',
        null=True, on_delete=models.SET_NULL)
    _latest_version = models.ForeignKey(Version, db_column='latest_version',
                                        on_delete=models.SET_NULL,
                                        null=True, related_name='+')
    make_public = models.DateTimeField(null=True)
    mozilla_contact = models.EmailField(blank=True)

    # Whether the app is packaged or not (aka hosted).
    is_packaged = models.BooleanField(default=False, db_index=True)

    # This gets overwritten in the transformer.
    share_counts = collections.defaultdict(int)

    enable_new_regions = models.BooleanField(default=False, db_index=True)

    objects = AddonManager()
    with_deleted = AddonManager(include_deleted=True)

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
        if ((len(args) == len(Addon._meta.fields) and
                args[type_idx] == amo.ADDON_WEBAPP) or kw and
                kw.get('type') == amo.ADDON_WEBAPP):
            raise RuntimeError
        return object.__new__(cls)

    def __unicode__(self):
        return u'%s: %s' % (self.id, self.name)

    def __init__(self, *args, **kw):
        super(Addon, self).__init__(*args, **kw)
        self._first_category = {}

    def save(self, **kw):
        self.clean_slug()
        super(Addon, self).save(**kw)

    @use_master
    def clean_slug(self, slug_field='slug'):
        if self.status == amo.STATUS_DELETED:
            return
        clean_slug(self, slug_field)

    @transaction.commit_on_success
    def delete(self, msg='', reason=''):
        # To avoid a circular import.
        from . import tasks
        # Check for soft deletion path. Happens only if the addon status isn't 0
        # (STATUS_INCOMPLETE).
        soft_deletion = self.highest_status or self.status
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

            if self.guid:
                log.debug('Adding guid to blacklist: %s' % self.guid)
                BlacklistedGuid(guid=self.guid, comments=msg).save()
            log.debug('Deleting add-on: %s' % self.id)

            to = [settings.FLIGTAR]
            user = amo.get_user()

            context = {
                'atype': amo.ADDON_TYPE.get(self.type).upper(),
                'authors': [u.email for u in self.authors.all()],
                'adu': self.average_daily_users,
                'guid': self.guid,
                'id': self.id,
                'msg': msg,
                'reason': reason,
                'name': self.name,
                'slug': self.slug,
                'total_downloads': self.total_downloads,
                'url': absolutify(self.get_url_path()),
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
            self.update(status=amo.STATUS_DELETED,
                        slug=None, app_slug=None, app_domain=None,
                        _current_version=None)
            models.signals.post_delete.send(sender=Addon, instance=self)

            send_mail(subject, email_msg, recipient_list=to)
        else:
            # Real deletion path.
            super(Addon, self).delete()

        for preview in previews:
            tasks.delete_preview_files.delay(preview)

        # Remove from search index.
        tasks.unindex_addons.delay([id])

        return True

    @classmethod
    def from_upload(cls, upload, platforms, is_packaged=False):
        from files.utils import parse_addon

        data = parse_addon(upload)
        fields = cls._meta.get_all_field_names()
        addon = Addon(**dict((k, v) for k, v in data.items() if k in fields))
        addon.status = amo.STATUS_NULL
        locale_is_set = (addon.default_locale and
                         addon.default_locale in (
                             settings.AMO_LANGUAGES +
                             settings.HIDDEN_LANGUAGES) and
                         data.get('default_locale') == addon.default_locale)
        if not locale_is_set:
            addon.default_locale = to_language(translation.get_language())
        addon.save()
        Version.from_upload(upload, addon, platforms)

        amo.log(amo.LOG.CREATE_ADDON, addon)
        log.debug('New addon %r from %r' % (addon, upload))

        return addon

    def flush_urls(self):
        urls = ['*/addon/%s/' % self.slug,  # Doesn't take care of api
                '*/addon/%s/developers/' % self.slug,
                '*/addon/%s/eula/*' % self.slug,
                '*/addon/%s/privacy/' % self.slug,
                '*/addon/%s/versions/*' % self.slug,
                '*/api/*/addon/%s' % self.slug,
                self.icon_url,
                self.thumbnail_url,
                ]
        urls.extend('*/user/%d/' % u.id for u in self.listed_authors)

        return urls

    def get_url_path(self, more=False, add_prefix=True):
        # If more=True you get the link to the ajax'd middle chunk of the
        # detail page.
        view = 'addons.detail_more' if more else 'addons.detail'
        return reverse(view, args=[self.slug], add_prefix=add_prefix)

    def get_api_url(self):
        # Used by Piston in output.
        return absolutify(self.get_url_path())

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
        return shared_url('reviews.list', self)

    def get_ratings_url(self, action='list', args=None, add_prefix=True):
        return reverse('ratings.themes.%s' % action,
                       args=[self.slug] + (args or []),
                       add_prefix=add_prefix)

    def type_url(self):
        """The url for this add-on's AddonType."""
        return AddonType(self.type).get_url_path()

    def share_url(self):
        return reverse('addons.share', args=[self.slug])

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
        lang = translation.to_language(self.default_locale)
        return settings.LANGUAGES.get(lang)

    @property
    def valid_file_statuses(self):
        if self.status == amo.STATUS_PUBLIC:
            return [amo.STATUS_PUBLIC]

        if self.status == amo.STATUS_PUBLIC_WAITING:
            # For public_waiting apps, accept both public and
            # public_waiting statuses, because the file status might be
            # changed from PUBLIC_WAITING to PUBLIC just before the app's
            # is.
            return amo.WEBAPPS_APPROVED_STATUSES

        if self.status in (amo.STATUS_LITE,
                           amo.STATUS_LITE_AND_NOMINATED):
            return [amo.STATUS_PUBLIC, amo.STATUS_LITE,
                    amo.STATUS_LITE_AND_NOMINATED]

        return amo.VALID_STATUSES

    def get_version(self, backup_version=False):
        """
        Retrieves the latest public version of an addon.
        backup_version: if specified the highest file up to but *not* including
                        this version will be found.
        """
        if self.type == amo.ADDON_PERSONA:
            return
        try:
            status = self.valid_file_statuses

            status_list = ','.join(map(str, status))
            fltr = {'files__status__in': status}
            if backup_version:
                fltr['apps__application__id'] = amo.FIREFOX.id
                fltr['apps__min__version_int__lt'] = amo.FIREFOX.backup_version
            return self.versions.no_cache().filter(**fltr).extra(
                where=["""
                    NOT EXISTS (
                        SELECT 1 FROM versions as v2
                        INNER JOIN files AS f2 ON (f2.version_id = v2.id)
                        WHERE v2.id = versions.id
                        AND f2.status NOT IN (%s))
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

        backup = None
        current = self.get_version()
        if current:
            firefox_min = current.compatible_apps.get(amo.FIREFOX)
            if (firefox_min and
                firefox_min.min.version_int > amo.FIREFOX.backup_version):
                backup = self.get_version(backup_version=True)

        try:
            latest_qs = self.versions.exclude(files__status=amo.STATUS_BETA)
            if ignore is not None:
                latest_qs = latest_qs.exclude(pk=ignore.pk)
            latest = latest_qs.latest()
        except Version.DoesNotExist:
            latest = None
        latest_id = latest and latest.id

        diff = [self._backup_version, backup, self._current_version, current]

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
        if self._backup_version != backup:
            updated.update({'_backup_version': backup})
            send_signal = True
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
            updated = dict([(k, v) for (k, v) in updated.iteritems() if v != ignore])

        if updated:
            # Pass along _signal to the .update() to prevent it from firing
            # signals if we don't want them.
            updated['_signal'] = _signal
            try:
                self.update(**updated)
                if send_signal and _signal:
                    signals.version_changed.send(sender=self)
                log.info(u'Version changed from backup: %s to %s, '
                          'current: %s to %s, latest: %s to %s for addon %s'
                          % tuple(diff + [self]))
            except Exception, e:
                log.error(u'Could not save version changes backup: %s to %s, '
                          'current: %s to %s, latest: %s to %s '
                          'for addon %s (%s)' %
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
                   'OS:%s, Mode:%s' % (self.id, app_id, app_version, platform,
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
            INNER JOIN applications
                ON applications_versions.application_id = applications.id
                AND applications.id = %(app_id)s
            INNER JOIN appversions appmin
                ON appmin.id = applications_versions.min
            INNER JOIN appversions appmax
                ON appmax.id = applications_versions.max
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
        cache.set(cache_key, version_id, 0)

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

    @property
    def backup_version(self):
        """Returns the backup version."""
        if not self.current_version:
            return
        return self._backup_version

    def get_icon_dir(self):
        return os.path.join(settings.ADDON_ICONS_PATH,
                            '%s' % (self.id / 1000))

    def get_icon_url(self, size, use_default=True):
        """
        Returns either the addon's icon url.
        If this is not a theme or persona and there is no
        icon for the addon then if:
            use_default is True, will return a default icon
            use_default is False, will return None
        """
        icon_type_split = []
        if self.icon_type:
            icon_type_split = self.icon_type.split('/')

        # Get the closest allowed size without going over
        if (size not in amo.ADDON_ICON_SIZES
                and size >= amo.ADDON_ICON_SIZES[0]):
            size = [s for s in amo.ADDON_ICON_SIZES if s < size][-1]
        elif size < amo.ADDON_ICON_SIZES[0]:
            size = amo.ADDON_ICON_SIZES[0]

        # Figure out what to return for an image URL
        if self.type == amo.ADDON_PERSONA:
            return self.persona.icon_url
        if not self.icon_type:
            if self.type == amo.ADDON_THEME:
                icon = amo.ADDON_ICONS[amo.ADDON_THEME]
                return settings.ADDON_ICON_BASE_URL + icon
            else:
                if not use_default:
                    return None
                return '%s/%s-%s.png' % (settings.ADDON_ICONS_DEFAULT_URL,
                                         'default', size)
        elif icon_type_split[0] == 'icon':
            return '%s/%s-%s.png' % (settings.ADDON_ICONS_DEFAULT_URL,
                                     icon_type_split[1], size)
        else:
            # [1] is the whole ID, [2] is the directory
            split_id = re.match(r'((\d*?)\d{1,3})$', str(self.id))
            return settings.ADDON_ICON_URL % (
                split_id.group(2) or 0, self.id, size,
                int(time.mktime(self.modified.timetuple())))

    @write
    def update_status(self):
        if (self.status in [amo.STATUS_NULL, amo.STATUS_DELETED]
            or self.is_disabled or self.is_persona() or self.is_webapp()):
            return

        def logit(reason, old=self.status):
            log.info('Changing add-on status [%s]: %s => %s (%s).'
                     % (self.id, old, self.status, reason))
            amo.log(amo.LOG.CHANGE_STATUS, self.get_status_display(), self)

        versions = self.versions.all()
        if not versions.exists():
            self.update(status=amo.STATUS_NULL)
            logit('no versions')
        elif not (versions.filter(files__isnull=False).exists()):
            self.update(status=amo.STATUS_NULL)
            logit('no versions with files')
        elif (self.status == amo.STATUS_PUBLIC and
              not versions.filter(files__status=amo.STATUS_PUBLIC).exists()):
            if versions.filter(files__status=amo.STATUS_LITE).exists():
                self.update(status=amo.STATUS_LITE)
                logit('only lite files')
            else:
                self.update(status=amo.STATUS_UNREVIEWED)
                logit('no reviewed files')

    @staticmethod
    def attach_related_versions(addons, addon_dict=None):
        if addon_dict is None:
            addon_dict = dict((a.id, a) for a in addons)

        current_ids = filter(None, (a._current_version_id for a in addons))
        latest_ids = filter(None, (a._latest_version_id for a in addons))
        backup_ids = filter(None, (a._backup_version_id for a in addons))
        all_ids = set(current_ids) | set(backup_ids) | set(latest_ids)

        versions = list(Version.objects.filter(id__in=all_ids).order_by())
        for version in versions:
            try:
                addon = addon_dict[version.addon_id]
            except KeyError:
                log.debug('Version %s has an invalid add-on id.' % version.id)
                continue
            if addon._current_version_id == version.id:
                addon._current_version = version
            if addon._backup_version_id == version.id:
                addon._backup_version = version
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

        # Set _backup_version, _latest_version, _current_version
        Addon.attach_related_versions(addons, addon_dict=addon_dict)

        # Attach listed authors.
        Addon.attach_listed_authors(addons, addon_dict=addon_dict)

        for persona in Persona.objects.no_cache().filter(addon__in=personas):
            addon = addon_dict[persona.addon_id]
            addon.persona = persona
            addon.weekly_downloads = persona.popularity

        # Personas need categories for the JSON dump.
        Category.transformer(personas)

        # Attach sharing stats.
        sharing.attach_share_counts(AddonShareCountTotal, 'addon', addon_dict)

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
        return self.type not in (amo.ADDON_SEARCH, amo.ADDON_WEBAPP)

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
                  .exclude(type=amo.ADDON_WEBAPP)
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
            return settings.MEDIA_URL + '/img/icons/no-preview.png'

    def can_request_review(self):
        """Return the statuses an add-on can request."""
        if not File.objects.filter(version__addon=self):
            return ()
        if (self.is_disabled or
            self.status in (amo.STATUS_PUBLIC,
                            amo.STATUS_LITE_AND_NOMINATED,
                            amo.STATUS_DELETED) or
            not self.latest_version or
            not self.latest_version.files.exclude(status=amo.STATUS_DISABLED)):
            return ()
        elif self.status == amo.STATUS_NOMINATED:
            return (amo.STATUS_LITE,)
        elif self.status == amo.STATUS_UNREVIEWED:
            return (amo.STATUS_PUBLIC,)
        elif self.status == amo.STATUS_LITE:
            if self.days_until_full_nomination() == 0:
                return (amo.STATUS_PUBLIC,)
            else:
                # Still in preliminary waiting period...
                return ()
        else:
            return (amo.STATUS_LITE, amo.STATUS_PUBLIC)

    def days_until_full_nomination(self):
        """Returns number of days until author can request full review.

        If wait period is over or this doesn't apply at all, returns 0 days.
        An author must wait 10 days after submitting first LITE approval
        to request FULL.
        """
        if self.status != amo.STATUS_LITE:
            return 0
        # Calculate wait time from the earliest submitted version:
        qs = (File.objects.filter(version__addon=self, status=self.status)
              .order_by('created').values_list('datestatuschanged'))[:1]
        if qs:
            days_ago = datetime.now() - qs[0][0]
            if days_ago < timedelta(days=10):
                return 10 - days_ago.days
        return 0

    def is_persona(self):
        return self.type == amo.ADDON_PERSONA

    def is_webapp(self):
        return self.type == amo.ADDON_WEBAPP

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
        return self.status in amo.STATUS_UNDER_REVIEW

    def is_unreviewed(self):
        return self.status in amo.UNREVIEWED_STATUSES

    def is_public(self):
        return self.status == amo.STATUS_PUBLIC and not self.disabled_by_user

    def is_public_waiting(self):
        return self.status == amo.STATUS_PUBLIC_WAITING

    def is_incomplete(self):
        return self.status == amo.STATUS_NULL

    def is_pending(self):
        return self.status == amo.STATUS_PENDING

    def is_rejected(self):
        return self.status == amo.STATUS_REJECTED

    def can_become_premium(self):
        """
        Not all addons can become premium and those that can only at
        certain times. Webapps can become premium at any time.
        """
        if self.upsell:
            return False
        if self.type == amo.ADDON_WEBAPP and not self.is_premium():
            return True
        return (self.status in amo.PREMIUM_STATUSES
                and self.highest_status in amo.PREMIUM_STATUSES
                and self.type in amo.ADDON_BECOME_PREMIUM)

    def is_premium(self):
        """
        If the addon is premium. Will include addons that are premium
        and have a price of zero. Primarily of use in the devhub to determine
        if an app is intending to be premium.
        """
        return self.premium_type in amo.ADDON_PREMIUMS

    def is_free(self):
        """
        This is the opposite of is_premium. Will not include apps that have a
        price of zero. Primarily of use in the devhub to determine if an app is
        intending to be free.
        """
        return not (self.is_premium() and self.premium and
                    self.premium.price)

    def is_free_inapp(self):
        return self.premium_type == amo.ADDON_FREE_INAPP

    def needs_payment(self):
        return (self.premium_type not in
                (amo.ADDON_FREE, amo.ADDON_OTHER_INAPP))

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
            return models.query.EmptyQuerySet(), tags
        user_tags = tags.exclude(addon_tags__user__in=self.listed_authors)
        dev_tags = tags.exclude(id__in=[t.id for t in user_tags])
        return dev_tags, user_tags

    @amo.cached_property
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
        return (self.status == amo.STATUS_PUBLIC and self.wants_contributions
                and (self.paypal_id or self.charity_id))

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
            Addon.objects.no_cache().filter(status=amo.STATUS_PUBLIC,
                                  versions__files__status=amo.STATUS_PUBLIC)
            .exclude(type__in=(amo.ADDON_PERSONA, amo.ADDON_WEBAPP))
            .values('id').annotate(last_updated=status_change))

        lite = (Addon.objects.no_cache().filter(status__in=amo.LISTED_STATUSES,
                                      versions__files__status=amo.STATUS_LITE)
                .exclude(type=amo.ADDON_WEBAPP)
                .values('id').annotate(last_updated=status_change))

        stati = amo.LISTED_STATUSES + (amo.STATUS_PUBLIC,)
        exp = (Addon.objects.no_cache().exclude(status__in=stati)
               .filter(versions__files__status__in=amo.VALID_STATUSES)
               .exclude(type=amo.ADDON_WEBAPP)
               .values('id')
               .annotate(last_updated=Max('versions__files__created')))

        personas = (Addon.objects.no_cache().filter(type=amo.ADDON_PERSONA)
                    .extra(select={'last_updated': 'created'}))
        webapps = (Addon.objects.no_cache()
                   .filter(type=amo.ADDON_WEBAPP,
                           status=amo.STATUS_PUBLIC,
                           versions__files__status=amo.STATUS_PUBLIC)
                   .values('id')
                   .annotate(last_updated=Max('versions__created')))

        return dict(public=public, exp=exp, personas=personas,
                    lite=lite, webapps=webapps)

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
                                    key=lambda x: x.application_id)
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
            ids = [getattr(o, f.attname) for f in o._meta.translated_fields]
            qs = Translation.objects.filter(id__in=filter(None, ids),
                                            locale=locale)
            qs.update(localized_string=None, localized_string_clean=None)

    def app_perf_results(self):
        """Generator of (AppVersion, [list of perf results contexts]).

        A performance result context is a dict that has these keys:

        **baseline**
            The baseline of the result. For startup time this is the
            time it takes to start up with no addons.

        **startup_is_too_slow**
            True/False if this result is slower than the threshold.

        **result**
            Actual result object
        """
        res = collections.defaultdict(list)
        baselines = {}
        for result in (self.performance
                       .select_related('osversion', 'appversion')
                       .order_by('-created')[:20]):
            k = (result.appversion.id, result.osversion.id, result.test)
            if k not in baselines:
                baselines[k] = result.get_baseline()
            baseline = baselines[k]
            appver = result.appversion
            slow = result.startup_is_too_slow(baseline=baseline)
            res[appver].append({'baseline': baseline,
                                'startup_is_too_slow': slow,
                                'result': result})
        return res.iteritems()

    def get_localepicker(self):
        """For language packs, gets the contents of localepicker."""
        if (self.type == amo.ADDON_LPAPP and self.status == amo.STATUS_PUBLIC
            and self.current_version):
            files = (self.current_version.files
                         .filter(platform__in=amo.MOBILE_PLATFORMS.keys()))
            try:
                return unicode(files[0].get_localepicker(), 'utf-8')
            except IndexError:
                pass
        return ''

    def get_mozilla_contacts(self):
        return [x.strip() for x in self.mozilla_contact.split(',')]

    def can_review(self, user):
        if user and self.has_author(user):
            return False
        else:
           return True

    @property
    def all_dependencies(self):
        """Return all the add-ons this add-on depends on."""
        return list(self.dependencies.all()[:3])

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

    @property
    def uses_flash(self):
        """
        Convenience property until more sophisticated per-version
        checking is done for packaged apps.
        """
        f = self.get_latest_file()
        if not f:
            return False
        return f.uses_flash

    def in_escalation_queue(self):
        return self.escalationqueue_set.exists()

    def sign_if_packaged(self, version_pk, reviewer=False):
        raise NotImplementedError('Not available for add-ons.')

    def update_names(self, new_names):
        """
        Adds, edits, or removes names to match the passed in new_names dict.
        Will not remove the translation of the default_locale.

        `new_names` is a dictionary mapping of locales to names.

        Returns a message that can be used in logs showing what names were
        added or updated.

        Note: This method doesn't save the changes made to the addon object.
        Don't forget to call save() in your calling method.
        """
        updated_locales = {}
        locales = dict(Translation.objects.filter(id=self.name_id)
                                          .values_list('locale',
                                                       'localized_string'))
        msg_c = []  # For names that were created.
        msg_d = []  # For deletes.
        msg_u = []  # For updates.

        # Normalize locales.
        names = {}
        for locale, name in new_names.iteritems():
            loc = find_language(locale)
            if loc and loc not in names:
                names[loc] = name

        # Null out names no longer in `names` but exist in the database.
        for locale in set(locales) - set(names):
            names[locale] = None

        for locale, name in names.iteritems():

            if locale in locales:
                if not name and locale.lower() == self.default_locale.lower():
                    pass  # We never want to delete the default locale.
                elif not name:  # A deletion.
                    updated_locales[locale] = None
                    msg_d.append(u'"%s" (%s).' % (locales.get(locale), locale))
                elif name != locales[locale]:
                    updated_locales[locale] = name
                    msg_u.append(u'"%s" -> "%s" (%s).' % (
                        locales[locale], name, locale))
            else:
                updated_locales[locale] = names.get(locale)
                msg_c.append(u'"%s" (%s).' % (name, locale))

        if locales != updated_locales:
            self.name = updated_locales

        return {
            'added': ' '.join(msg_c),
            'deleted': ' '.join(msg_d),
            'updated': ' '.join(msg_u),
        }

    def update_default_locale(self, locale):
        """
        Updates default_locale if it's different and matches one of our
        supported locales.

        Returns tuple of (old_locale, new_locale) if updated. Otherwise None.
        """
        old_locale = self.default_locale
        locale = find_language(locale)
        if locale and locale != old_locale:
            self.update(default_locale=locale)
            return old_locale, locale
        return None

    @property
    def app_type(self):
        # Not implemented for non-webapps.
        return ''

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

dbsignals.pre_save.connect(save_signal, sender=Addon,
                           dispatch_uid='addon_translations')


class AddonDeviceType(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)
    device_type = models.PositiveIntegerField(
        default=amo.DEVICE_DESKTOP, choices=do_dictsort(amo.DEVICE_TYPES),
        db_index=True)

    class Meta:
        db_table = 'addons_devicetypes'
        unique_together = ('addon', 'device_type')

    def __unicode__(self):
        return u'%s: %s' % (self.addon.name, self.device.name)

    @property
    def device(self):
        return amo.DEVICE_TYPES[self.device_type]


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
    """Set nomination date if self.status asks for full review.

    The nomination date will only be set when the status of the addon changes.
    The nomination date cannot be reset, say, when a developer cancels their
    request for full review and re-requests full review.

    If a version is rejected after nomination, the developer has to upload a
    new version.
    """
    new_status = new_attr.get('status')
    if not new_status:
        return
    addon = instance
    stati = (amo.STATUS_NOMINATED, amo.STATUS_LITE_AND_NOMINATED)
    if new_status in stati and old_attr['status'] != new_status:
        try:
            latest = addon.versions.latest()
            if not latest.nomination:
                latest.update(nomination=datetime.now())
        except Version.DoesNotExist:
            pass


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


def attach_devices(addons):
    addon_dict = dict((a.id, a) for a in addons if a.type == amo.ADDON_WEBAPP)
    devices = (AddonDeviceType.objects.filter(addon__in=addon_dict)
               .values_list('addon', 'device_type'))
    for addon, device_types in sorted_groupby(devices, lambda x: x[0]):
        addon_dict[addon].device_ids = [d[1] for d in device_types]


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
    addon = models.OneToOneField(Addon)
    persona_id = models.PositiveIntegerField(db_index=True)
    # name: deprecated in favor of Addon model's name field
    # description: deprecated, ditto
    header = models.CharField(max_length=64, null=True)
    footer = models.CharField(max_length=64, null=True)
    accentcolor = models.CharField(max_length=10, null=True)
    textcolor = models.CharField(max_length=10, null=True)
    author = models.CharField(max_length=32, null=True)
    display_username = models.CharField(max_length=32, null=True)
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

    def flush_urls(self):
        urls = ['*/addon/%d/' % self.addon_id,
                '*/api/*/addon/%d' % self.addon_id,
                self.thumb_url,
                self.icon_url,
                self.preview_url,
                self.header_url,
                self.footer_url,
                self.update_url]
        return urls

    def _image_url(self, filename):
        return self.get_mirror_url(filename)

    def _image_path(self, filename):
        return os.path.join(settings.ADDONS_PATH, str(self.addon.id), filename)

    def get_mirror_url(self, filename):
        host = (settings.PRIVATE_MIRROR_URL if self.addon.is_disabled
                else settings.LOCAL_MIRROR_URL)
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
        return self._image_url(self.footer)

    @amo.cached_property
    def header_path(self):
        return self._image_path(self.header)

    @amo.cached_property
    def footer_path(self):
        return self._image_path(self.footer)

    @amo.cached_property
    def update_url(self):
        locale = settings.LANGUAGE_URL_MAP.get(translation.get_language())
        return settings.NEW_PERSONAS_UPDATE_URL % {
            'locale': locale or settings.LANGUAGE_CODE,
            'id': self.addon.id
        }

    @amo.cached_property
    def theme_data(self):
        """Theme JSON Data for Browser/extension preview."""
        hexcolor = lambda color: '#%s' % color
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
            'footer': self.footer_url,
            'headerURL': self.header_url,
            'footerURL': self.footer_url,
            'previewURL': self.thumb_url,
            'iconURL': self.icon_url,
            'updateURL': self.update_url,
            'detailURL': absolutify(self.addon.get_url_path()),
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
        # TODO(andym): delete this once personas are migrated.
        if not waffle.switch_is_active('personas-migration-completed'):
            return (qs.filter(persona__author=self.author)
                      .select_related('persona'))
        return (qs.filter(addonuser__listed=True,
                          authors__in=self.addon.listed_authors)
                  .distinct())

    @amo.cached_property(writable=True)
    def listed_authors(self):
        # TODO(andym): delete this once personas are migrated.
        if not waffle.switch_is_active('personas-migration-completed'):

            class PersonaAuthor(unicode):
                @property
                def name(self):
                    return self
            return [PersonaAuthor(self.display_username)]
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

    def flush_urls(self):
        urls = ['*/addon/%d/' % self.addon_id,
                '*%s' % self.category.get_url_path(), ]
        return urls

    @classmethod
    def creatured_random(cls, category, lang):
        return get_creatured_ids(category, lang)


class AddonRecommendation(models.Model):
    """
    Add-on recommendations. For each `addon`, a group of `other_addon`s
    is recommended with a score (= correlation coefficient).
    """
    addon = models.ForeignKey(Addon, related_name="addon_recommendations")
    other_addon = models.ForeignKey(Addon, related_name="recommended_for")
    score = models.FloatField()

    class Meta:
        db_table = 'addon_recommendations'
        ordering = ('-score',)

    @classmethod
    def scores(cls, addon_ids):
        """Get a mapping of {addon: {other_addon: score}} for each add-on."""
        d = {}
        q = (AddonRecommendation.objects.filter(addon__in=addon_ids)
             .values('addon', 'other_addon', 'score'))
        for addon, rows in sorted_groupby(q, key=lambda x: x['addon']):
            d[addon] = dict((r['other_addon'], r['score']) for r in rows)
        return d


class AddonType(amo.models.ModelBase):
    name = TranslatedField()
    name_plural = TranslatedField()
    description = TranslatedField()

    class Meta:
        db_table = 'addontypes'

    def __unicode__(self):
        return unicode(self.name)

    def get_url_path(self):
        try:
            type = amo.ADDON_SLUGS[self.id]
        except KeyError:
            return None
        return reverse('browse.%s' % type)

dbsignals.pre_save.connect(save_signal, sender=AddonType,
                           dispatch_uid='addontype_translations')


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

    def flush_urls(self):
        return self.addon.flush_urls() + self.user.flush_urls()


class AddonDependency(models.Model):
    addon = models.ForeignKey(Addon, related_name='addons_dependencies')
    dependent_addon = models.ForeignKey(Addon, related_name='dependent_on')

    class Meta:
        db_table = 'addons_dependencies'
        unique_together = ('addon', 'dependent_addon')


class BlacklistedGuid(amo.models.ModelBase):
    guid = models.CharField(max_length=255, unique=True)
    comments = models.TextField(default='', blank=True)

    class Meta:
        db_table = 'blacklisted_guids'

    def __unicode__(self):
        return self.guid


class Category(amo.models.OnChangeMixin, amo.models.ModelBase):
    name = TranslatedField()
    slug = amo.models.SlugField(max_length=50,
                                help_text='Used in Category URLs.')
    type = models.PositiveIntegerField(db_column='addontype_id',
                                       choices=do_dictsort(amo.ADDON_TYPE))
    application = models.ForeignKey('applications.Application', null=True,
                                    blank=True)
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

    def flush_urls(self):
        urls = ['*%s' % self.get_url_path(), ]
        return urls

    def get_url_path(self):
        try:
            type = amo.ADDON_SLUGS[self.type]
        except KeyError:
            type = amo.ADDON_SLUGS[amo.ADDON_EXTENSION]
        if self.type == amo.ADDON_PERSONA:
            return 'https://addons.mozilla.org/firefox/themes/%s' % self.slug
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


class Feature(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)
    start = models.DateTimeField()
    end = models.DateTimeField()
    locale = models.CharField(max_length=10, default='', blank=True, null=True)
    application = models.ForeignKey('applications.Application')

    class Meta:
        db_table = 'features'

    def __unicode__(self):
        app = amo.APP_IDS[self.application.id].pretty
        return '%s (%s: %s)' % (self.addon.name, app, self.locale)


class Preview(amo.models.ModelBase):
    addon = models.ForeignKey(Addon, related_name='previews')
    filetype = models.CharField(max_length=25)
    thumbtype = models.CharField(max_length=25)
    caption = TranslatedField()

    position = models.IntegerField(default=0)
    sizes = json_field.JSONField(max_length=25, default={})

    class Meta:
        db_table = 'previews'
        ordering = ('position', 'created')

    def flush_urls(self):
        urls = ['*/addon/%d/' % self.addon_id,
                self.thumbnail_url,
                self.image_url, ]
        return urls

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
        return self._image_url(settings.PREVIEW_THUMBNAIL_URL)

    @property
    def image_url(self):
        return self._image_url(settings.PREVIEW_FULL_URL)

    @property
    def thumbnail_path(self):
        return self._image_path(settings.PREVIEW_THUMBNAIL_PATH)

    @property
    def image_path(self):
        return self._image_path(settings.PREVIEW_FULL_PATH)

    @property
    def thumbnail_size(self):
        return self.sizes.get('thumbnail', []) if self.sizes else []

    @property
    def image_size(self):
        return self.sizes.get('image', []) if self.sizes else []

dbsignals.pre_save.connect(save_signal, sender=Preview,
                           dispatch_uid='preview_translations')


class AppSupport(amo.models.ModelBase):
    """Cache to tell us if an add-on's current version supports an app."""
    addon = models.ForeignKey(Addon)
    app = models.ForeignKey('applications.Application')
    min = models.BigIntegerField("Minimum app version", null=True)
    max = models.BigIntegerField("Maximum app version", null=True)

    class Meta:
        db_table = 'appsupport'
        unique_together = ('addon', 'app')


class Charity(amo.models.ModelBase):
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


class BlacklistedSlug(amo.models.ModelBase):
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


class AddonUpsell(amo.models.ModelBase):
    free = models.ForeignKey(Addon, related_name='_upsell_from')
    premium = models.ForeignKey(Addon, related_name='_upsell_to')

    class Meta:
        db_table = 'addon_upsell'
        unique_together = ('free', 'premium')

    def __unicode__(self):
        return u'Free: %s to Premium: %s' % (self.free, self.premium)

    @amo.cached_property
    def premium_addon(self):
        """
        Return the premium version, or None if there isn't one.
        """
        try:
            return self.premium
        except Addon.DoesNotExist:
            pass

    def cleanup(self):
        try:
            # Just accessing these may raise an error.
            assert self.free and self.premium
        except ObjectDoesNotExist:
            log.info('Deleted upsell: from %s, to %s' %
                     (self.free_id, self.premium_id))
            self.delete()


def cleanup_upsell(sender, instance, **kw):
    if 'raw' in kw:
        return

    both = Q(free=instance) | Q(premium=instance)
    for upsell in list(AddonUpsell.objects.filter(both)):
        upsell.cleanup()

dbsignals.post_delete.connect(cleanup_upsell, sender=Addon,
                              dispatch_uid='addon_upsell')


class CompatOverride(amo.models.ModelBase):
    """Helps manage compat info for add-ons not hosted on AMO."""
    name = models.CharField(max_length=255, blank=True, null=True)
    guid = models.CharField(max_length=255, unique=True)
    addon = models.ForeignKey(Addon, blank=True, null=True,
                              help_text='Fill this out to link an override '
                                        'to a hosted add-on')

    class Meta:
        db_table = 'compat_override'

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
        sort_key = lambda x: (x.min_version, x.max_version, x.type)
        for key, compats in sorted_groupby(self.compat_ranges, key=sort_key):
            compats = list(compats)
            first = compats[0]
            item = Range(first.override_type(), first.min_version,
                         first.max_version, [])
            for compat in compats:
                app = AppRange(amo.APPS_ALL[compat.app_id],
                               compat.min_app_version, compat.max_app_version)
                item.apps.append(app)
            rv.append(item)
        return rv


OVERRIDE_TYPES = (
    (0, 'Compatible (not supported)'),
    (1, 'Incompatible'),
)


class CompatOverrideRange(amo.models.ModelBase):
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
    app = models.ForeignKey('applications.Application')
    min_app_version = models.CharField(max_length=255, default='0')
    max_app_version = models.CharField(max_length=255, default='*')

    class Meta:
        db_table = 'compat_override_range'

    def override_type(self):
        """This is what Firefox wants to see in the XML output."""
        return {0: 'compatible', 1: 'incompatible'}[self.type]


class IncompatibleVersions(amo.models.ModelBase):
    """
    Denormalized table to join against for fast compat override filtering.

    This was created to be able to join against a specific version record since
    the CompatOverrideRange can be wildcarded (e.g. 0 to *, or 1.0 to 1.*), and
    addon versioning isn't as consistent as Firefox versioning to trust
    `version_int` in all cases.  So extra logic needed to be provided for when
    a particular version falls within the range of a compatibility override.
    """
    version = models.ForeignKey(Version, related_name='+')
    app = models.ForeignKey('applications.Application', related_name='+')
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
