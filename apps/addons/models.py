# -*- coding: utf-8 -*-
import collections
import hashlib
import hmac
import itertools
import json
import os
import re
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction
from django.dispatch import receiver
from django.db.models import Q, Max, signals as dbsignals
from django.utils.translation import trans_real as translation
from jinja2.filters import do_dictsort

import caching.base as caching
import commonware.log
import json_field
import waffle
from tower import ugettext_lazy as _

from addons.utils import get_featured_ids, get_creatured_ids

import amo.models
import mkt.constants
from amo.decorators import use_master
from amo.fields import DecimalCharField
from amo.helpers import absolutify, shared_url
from amo.utils import (cache_ns_key, chunked, find_language, JSONEncoder,
                       send_mail, slugify, sorted_groupby, to_language,
                       urlparams, timer)
from amo.urlresolvers import get_outgoing_url, reverse
from compat.models import CompatReport
from files.models import File
from market.models import AddonPremium, Price
from reviews.models import Review
import sharing.utils as sharing
from stats.models import AddonShareCountTotal
from translations.fields import (TranslatedField, PurifiedField,
                                 LinkifiedField, Translation)
from translations.query import order_by_translation
from users.models import UserProfile, UserForeignKey
from users.utils import find_users
from versions.compare import version_int
from versions.models import Version

from . import query, signals

log = commonware.log.getLogger('z.addons')


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

    def valid_and_disabled(self):
        """Get valid, enabled and disabled add-ons."""
        statuses = list(amo.LISTED_STATUSES) + [amo.STATUS_DISABLED]
        return self.filter(Q(status__in=statuses) | Q(disabled_by_user=True),
                           _current_version__isnull=False)

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

    def top_free(self, app, listed=True):
        qs = (self.listed(app) if listed else
              self.filter(appsupport__app=app.id))
        return (qs.exclude(premium_type__in=amo.ADDON_PREMIUMS)
                .exclude(addonpremium__price__price__isnull=False)
                .order_by('-weekly_downloads')
                .with_index(addons='downloads_type_idx'))

    def top_paid(self, app, listed=True):
        qs = (self.listed(app) if listed else
              self.filter(appsupport__app=app.id))
        return (qs.filter(premium_type__in=amo.ADDON_PREMIUMS,
                          addonpremium__price__price__isnull=False)
                .order_by('-weekly_downloads')
                .with_index(addons='downloads_type_idx'))

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
    app_slug = models.CharField(max_length=30, unique=True, null=True)
    name = TranslatedField()
    default_locale = models.CharField(max_length=10,
                                      default=settings.LANGUAGE_CODE,
                                      db_column='defaultlocale')

    type = models.PositiveIntegerField(db_column='addontype_id')
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

    get_satisfaction_company = models.CharField(max_length=255, blank=True,
                                                null=True)
    get_satisfaction_product = models.CharField(max_length=255, blank=True,
                                                null=True)

    authors = models.ManyToManyField('users.UserProfile', through='AddonUser',
                                     related_name='addons')
    categories = models.ManyToManyField('Category', through='AddonCategory')
    dependencies = models.ManyToManyField('self', symmetrical=False,
                                          through='AddonDependency',
                                          related_name='addons')
    premium_type = models.PositiveIntegerField(
        choices=amo.ADDON_PREMIUM_TYPES.items(), default=amo.ADDON_FREE)
    manifest_url = models.URLField(max_length=255, blank=True, null=True,
                                   verify_exists=False)
    app_domain = models.CharField(max_length=255, blank=True, null=True,
                                  db_index=True)

    _current_version = models.ForeignKey(
        Version, related_name='___ignore', db_column='current_version',
        null=True, on_delete=models.SET_NULL)
    # This is for Firefox only.
    _backup_version = models.ForeignKey(
        Version, related_name='___backup', db_column='backup_version',
        null=True, on_delete=models.SET_NULL)
    _latest_version = None
    make_public = models.DateTimeField(null=True)
    mozilla_contact = models.EmailField()

    # Whether the app is packaged or not (aka hosted).
    is_packaged = models.BooleanField(default=False, db_index=True)

    # This gets overwritten in the transformer.
    share_counts = collections.defaultdict(int)

    objects = AddonManager()
    with_deleted = AddonManager(include_deleted=True)

    class Meta:
        db_table = 'addons'

    @staticmethod
    def __new__(cls, *args, **kw):
        # Return a Webapp instead of an Addon if the `type` column says this is
        # really a webapp.
        try:
            type_idx = Addon._meta._type_idx
        except AttributeError:
            type_idx = (idx for idx, f in enumerate(Addon._meta.fields)
                        if f.attname == 'type').next()
            Addon._meta._type_idx = type_idx
        if ((len(args) == len(Addon._meta.fields) and
                args[type_idx] == amo.ADDON_WEBAPP) or kw and
                kw.get('type') == amo.ADDON_WEBAPP):
            cls = Webapp
        return super(Addon, cls).__new__(cls, *args, **kw)

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

        slug = getattr(self, slug_field, None)
        if not slug:
            if not self.name:
                try:
                    name = Translation.objects.filter(id=self.name_id)[0]
                except IndexError:
                    name = str(self.id)
            else:
                name = self.name
            slug = slugify(name)[:27]
        if BlacklistedSlug.blocked(slug):
            slug += '~'
        qs = Addon.objects.values_list(slug_field, 'id')
        match = qs.filter(**{slug_field: slug})
        if match and match[0][1] != self.id:
            if self.id:
                prefix = '%s-%s' % (slug[:-len(str(self.id))], self.id)
            else:
                prefix = slug
            slugs = dict(qs.filter(
                **{'%s__startswith' % slug_field: '%s-' % prefix}))
            slugs.update(match)
            for idx in range(len(slugs)):
                new = ('%s-%s' % (prefix, idx + 1))[:30]
                if new not in slugs:
                    slug = new
                    break
        setattr(self, slug_field, slug)

    @transaction.commit_on_success
    def delete(self, msg=''):
        id = self.id
        previews = list(Preview.objects.filter(addon__id=id)
                        .values_list('id', flat=True))
        if self.highest_status or self.status:
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
            """ % context
            log.debug('Sending delete email for %(atype)s %(id)s' % context)
            subject = 'Deleting %(atype)s %(slug)s (%(id)d)' % context
            if waffle.switch_is_active('soft_delete'):
                models.signals.pre_delete.send(sender=Addon, instance=self)
                self.status = amo.STATUS_DELETED
                self.slug = self.app_slug = self.app_domain = None
                self.save()
                models.signals.post_delete.send(sender=Addon, instance=self)
            else:
                super(Addon, self).delete()
            send_mail(subject, email_msg, recipient_list=to)
        else:
            super(Addon, self).delete()
        from . import tasks
        for preview in previews:
            tasks.delete_preview_files.delay(preview)
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
                         addon.default_locale != settings.LANGUAGE_CODE)
        if not locale_is_set:
            addon.default_locale = to_language(translation.get_language())
        if addon.is_webapp():
            addon.is_packaged = is_packaged
            if not is_packaged:
                addon.manifest_url = upload.name
                addon.app_domain = addon.domain_from_url(addon.manifest_url)
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
        if settings.MARKETPLACE and self.is_persona():
            return reverse('themes.detail', args=[self.slug])
        view = 'addons.detail_more' if more else 'addons.detail'
        return reverse(view, args=[self.slug], add_prefix=add_prefix)

    def get_api_url(self):
        # Used by Piston in output.
        return absolutify(self.get_url_path())

    def get_dev_url(self, action='edit', args=None, prefix_only=False):
        # Either link to the "new" Marketplace Developer Hub or the old one.
        args = args or []
        prefix = ('mkt.developers' if getattr(settings, 'MARKETPLACE', False)
                  else 'devhub')
        if self.is_webapp():
            view_name = '%s.%s' if prefix_only else '%s.apps.%s'
            return reverse(view_name % (prefix, action),
                           args=[self.app_slug] + args)
        else:
            view_name = '%s.%s' if prefix_only else '%s.addons.%s'
            return reverse(view_name % (prefix, action),
                           args=[self.slug] + args)

    def get_detail_url(self, action='detail', args=[]):
        if self.is_webapp():
            return reverse('apps.%s' % action, args=[self.app_slug] + args)
        else:
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

    def get_version(self, backup_version=False):
        """
        Retrieves the latest version of an addon.
        backup_version: if specified the highest file up to but *not* including
                        this version will be found.
        """
        if self.type == amo.ADDON_PERSONA:
            return
        try:
            if self.status == amo.STATUS_PUBLIC:
                status = [self.status]
            elif self.status in (amo.STATUS_LITE,
                                 amo.STATUS_LITE_AND_NOMINATED):
                status = [amo.STATUS_PUBLIC, amo.STATUS_LITE,
                          amo.STATUS_LITE_AND_NOMINATED]
            else:
                status = amo.VALID_STATUSES

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

    def update_version(self):
        "Returns true if we updated the field."
        backup = None
        current = self.get_version()
        if current:
            firefox_min = current.compatible_apps.get(amo.FIREFOX)
            if (firefox_min and
                firefox_min.min.version_int > amo.FIREFOX.backup_version):
                backup = self.get_version(backup_version=True)

        diff = [self._backup_version, backup, self._current_version, current]

        updated = {}
        if self._backup_version != backup:
            updated.update({'_backup_version': backup})
        if self._current_version != current:
            updated.update({'_current_version': current})

        if updated:
            try:
                self.update(**updated)
                signals.version_changed.send(sender=self)
                log.info(u'Version changed from backup: %s to %s, '
                          'current: %s to %s for addon %s'
                          % tuple(diff + [self]))
            except Exception, e:
                log.error(u'Could not save version changes backup: %s to %s, '
                          'current: %s to %s for addon %s (%s)' %
                          tuple(diff + [self, e]))

        return bool(updated)

    @property
    def latest_version(self):
        """Returns the absolutely newest non-beta version. """
        if self.type == amo.ADDON_PERSONA:
            return
        if not self._latest_version:
            try:
                v = (self.versions.exclude(files__status=amo.STATUS_BETA)
                                  .latest())
                self._latest_version = v
            except Version.DoesNotExist:
                self._latest_version = None

        return self._latest_version

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

        log.info(u'Checking compatibility for add-on ID:%s, APP:%s, V:%s, '
                  'OS:%s, Mode:%s' % (self.id, app_id, app_version, platform,
                                      compat_mode))
        valid_file_statuses = ','.join(map(str, amo.REVIEWED_STATUSES))
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
            log.info(u'Found compatible version in cache: %s => %s' % (
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

        log.info(u'Caching compat version %s => %s' % (cache_key, version_id))
        cache.set(cache_key, version_id, 0)

        return version

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
        "Returns the current_version field or updates it if needed."
        if self.type == amo.ADDON_PERSONA:
            return
        try:
            if not self._current_version:
                self.update_version()
        except ObjectDoesNotExist:
            return
        return self._current_version

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
        if not self._current_version:
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

    def update_status(self, using=None):
        if (self.status in [amo.STATUS_NULL, amo.STATUS_DELETED]
            or self.is_disabled or self.is_persona() or self.is_webapp()):
            return

        def logit(reason, old=self.status):
            log.info('Changing add-on status [%s]: %s => %s (%s).'
                     % (self.id, old, self.status, reason))
            amo.log(amo.LOG.CHANGE_STATUS, self.get_status_display(), self)

        versions = self.versions.using(using)
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
    @timer
    def transformer(addons):
        if not addons:
            return

        addon_dict = dict((a.id, a) for a in addons)
        non_apps = [a for a in addons if a.type != amo.ADDON_WEBAPP]
        personas = [a for a in addons if a.type == amo.ADDON_PERSONA]
        addons = [a for a in addons if a.type != amo.ADDON_PERSONA]

        version_ids = filter(None, (a._current_version_id for a in addons))
        backup_ids = filter(None, (a._backup_version_id for a in addons))
        all_ids = set(version_ids) | set(backup_ids)
        versions = list(Version.objects.filter(id__in=all_ids).order_by()
                        .transform(Version.transformer))
        for version in versions:
            addon = addon_dict[version.addon_id]
            if addon._current_version_id == version.id:
                addon._current_version = version
            elif addon._backup_version_id == version.id:
                addon._backup_version = version
            version.addon = addon

        # Attach listed authors.
        q = (UserProfile.objects.no_cache()
             .filter(addons__in=addons, addonuser__listed=True)
             .extra(select={'addon_id': 'addons_users.addon_id',
                            'position': 'addons_users.position'}))
        q = sorted(q, key=lambda u: (u.addon_id, u.position))
        for addon_id, users in itertools.groupby(q, key=lambda u: u.addon_id):
            addon_dict[addon_id].listed_authors = list(users)

        for persona in Persona.objects.no_cache().filter(addon__in=personas):
            addon = addon_dict[persona.addon_id]
            addon.persona = persona
            addon.weekly_downloads = persona.popularity

        # Personas need categories for the JSON dump.
        Category.transformer(personas)

        # Attach sharing stats.
        sharing.attach_share_counts(AddonShareCountTotal, 'addon', addon_dict)

        # Attach previews.
        qs = Preview.objects.filter(addon__in=addons,
                                    position__gte=0).order_by()
        qs = sorted(qs, key=lambda x: (x.addon_id, x.position, x.created))
        for addon, previews in itertools.groupby(qs, lambda x: x.addon_id):
            addon_dict[addon].all_previews = list(previews)

        # Attach _first_category for Firefox.
        cats = dict(AddonCategory.objects.values_list('addon', 'category')
                    .filter(addon__in=addon_dict,
                            category__application=amo.FIREFOX.id))
        qs = Category.objects.filter(id__in=set(cats.values()))
        categories = dict((c.id, c) for c in qs)
        for addon in addons:
            category = categories[cats[addon.id]] if addon.id in cats else None
            addon._first_category[amo.FIREFOX.id] = category

        # There's a constrained amount of price tiers, may as well load
        # them all and let cache machine keep them cached.
        prices = dict((p.id, p) for p in Price.objects.all())
        # Attach premium addons.
        qs = AddonPremium.objects.filter(addon__in=addons)
        for addon_p in qs:
            if addon_dict[addon_p.addon_id].is_premium():
                price = prices.get(addon_p.price_id)
                if price:
                    addon_p.price = price
                    addon_dict[addon_p.addon_id]._premium = addon_p

        # This isn't cheating, right? I don't want to add `compat` to
        # market's INSTALLED_APPS.
        if not settings.MARKETPLACE:
            # Attach counts for add-on compatibility reports.
            CompatReport.transformer(non_apps)

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

    def has_flag(self, flag_name):
        """Lookup boolean flag.

        False if flag isn't set or doesn't exist.
        """
        try:
            flag = getattr(self.flag, flag_name, False)
        except Flag.DoesNotExist:
            flag = False
        return flag

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

    def is_selfhosted(self):
        return self.status == amo.STATUS_LISTED

    @property
    def is_under_review(self):
        return self.status in amo.STATUS_UNDER_REVIEW

    def is_unreviewed(self):
        return self.status in amo.UNREVIEWED_STATUSES

    def is_public(self):
        return self.status == amo.STATUS_PUBLIC and not self.disabled_by_user

    def is_incomplete(self):
        return self.status == amo.STATUS_NULL

    def is_pending(self):
        return self.status == amo.STATUS_PENDING

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
                    self.premium.has_price())

    def needs_paypal(self):
        return (self.premium_type not in
                (amo.ADDON_FREE, amo.ADDON_OTHER_INAPP))

    def can_be_purchased(self):
        return self.is_premium() and self.status in amo.REVIEWED_STATUSES

    def can_be_deleted(self):
        """Only incomplete or free addons can be deleted."""
        if waffle.switch_is_active('soft_delete'):
            return not self.is_deleted
        return self.is_incomplete() or not (
            self.is_premium() or self.is_webapp())

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

    @caching.cached_method
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
            Addon.uncached.filter(status=amo.STATUS_PUBLIC,
                                  versions__files__status=amo.STATUS_PUBLIC)
            .exclude(type__in=(amo.ADDON_PERSONA, amo.ADDON_WEBAPP))
            .values('id').annotate(last_updated=status_change))

        lite = (Addon.uncached.filter(status__in=amo.LISTED_STATUSES,
                                      versions__files__status=amo.STATUS_LITE)
                .exclude(type=amo.ADDON_WEBAPP)
                .values('id').annotate(last_updated=status_change))

        stati = amo.LISTED_STATUSES + (amo.STATUS_PUBLIC,)
        exp = (Addon.uncached.exclude(status__in=stati)
               .filter(versions__files__status__in=amo.VALID_STATUSES)
               .exclude(type=amo.ADDON_WEBAPP)
               .values('id')
               .annotate(last_updated=Max('versions__files__created')))

        listed = (Addon.uncached.filter(status=amo.STATUS_LISTED)
                  .values('id')
                  .annotate(last_updated=Max('versions__created')))

        personas = (Addon.uncached.filter(type=amo.ADDON_PERSONA)
                    .extra(select={'last_updated': 'created'}))
        webapps = (
            Addon.uncached.filter(type=amo.ADDON_WEBAPP,
                                  status=amo.STATUS_PUBLIC,
                                  versions__files__status=amo.STATUS_PUBLIC)
                          .values('id')
                          .annotate(last_updated=Max('versions__created')))

        return dict(public=public, exp=exp, listed=listed, personas=personas,
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

    @amo.cached_property
    def upsell(self):
        """Return the upsell or add-on, or None if there isn't one."""
        try:
            # We set unique_together on the model, so there will only be one.
            return self._upsell_from.all()[0]
        except IndexError:
            pass

    @amo.cached_property
    def upsold(self):
        """
        Return what this is going to upsold from,
        or None if there isn't one.
        """
        try:
            return self._upsell_to.all()[0]
        except IndexError:
            pass

    def get_purchase_type(self, user):
        if user and isinstance(user, UserProfile):
            try:
                return self.addonpurchase_set.get(user=user).type
            except models.ObjectDoesNotExist:
                pass

    def has_purchased(self, user):
        return self.get_purchase_type(user) == amo.CONTRIB_PURCHASE

    def is_refunded(self, user):
        return self.get_purchase_type(user) == amo.CONTRIB_REFUND

    def is_chargeback(self, user):
        return self.get_purchase_type(user) == amo.CONTRIB_CHARGEBACK

    def can_review(self, user):
        if user and self.has_author(user):
            return False
        else:
            return (not self.is_premium() or self.has_purchased(user) or
                    self.is_refunded(user))

    @property
    def premium(self):
        """
        Returns the premium object which will be gotten by the transformer,
        if its not there, try and get it. Will return None if there's nothing
        there.
        """
        if not hasattr(self, '_premium'):
            try:
                self._premium = self.addonpremium
            except AddonPremium.DoesNotExist:
                self._premium = None
        return self._premium

    @property
    def all_dependencies(self):
        """Return all the add-ons this add-on depends on."""
        return list(self.dependencies.all()[:3])

    def get_watermark_hash(self, user):
        """
        Create a hash for the addon using the user and addon. Suitable for
        receipts or addon updates.
        """
        keys = [user.pk, time.mktime(user.created.timetuple()),
                self.pk, time.mktime(self.created.timetuple())]
        return hmac.new(settings.WATERMARK_SECRET_KEY,
                        ''.join(map(str, keys)),
                        hashlib.sha512).hexdigest()

    def get_user_from_hash(self, email, hsh):
        """
        Will try and match the watermark hash against a series of users,
        based on any users who has had the addon. Will return the user
        if it's found the person, otherwise None.
        """
        for user in find_users(email):
            if hsh == self.get_watermark_hash(user):
                return user

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

    def in_rereview_queue(self):
        # Rereview is part of marketplace and not AMO, so setting for False
        # to avoid having to catch NotImplemented errors.
        return False

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
        msg_c = []  # For names that were created messaging.
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
        if settings.IN_TEST_SUITE:
            tasks.index_addon_held([instance.id])
        else:
            tasks.index_addons([instance.id])


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
    license = models.ForeignKey('versions.License', null=True)

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

    def _image_url(self, filename, ssl=True):
        if self.is_new():
            return settings.NEW_PERSONAS_IMAGE_URL % {'id': self.addon.id,
                                                      'file': filename}
        else:
            # TODO(cvan): Remove when getpersonas.com images go bye-bye.
            base_url = (settings.PERSONAS_IMAGE_URL_SSL if ssl else
                        settings.PERSONAS_IMAGE_URL)
            return base_url % {
                'units': self.persona_id % 10,
                'tens': (self.persona_id // 10) % 10,
                'id': self.persona_id,
                'file': filename,
            }

    @amo.cached_property
    def thumb_url(self):
        """URL to Persona's thumbnail preview."""
        if self.is_new():
            return self._image_url('preview.png')
        else:
            return self._image_url('preview.jpg')

    @amo.cached_property
    def icon_url(self):
        """URL to personas square preview."""
        if self.is_new():
            return self._image_url('icon.png')
        else:
            return self._image_url('preview_small.jpg')

    @amo.cached_property
    def preview_url(self):
        """URL to Persona's big, 680px, preview."""
        if self.is_new():
            return self._image_url('preview.png')
        else:
            return self._image_url('preview_large.jpg')

    @amo.cached_property
    def header_url(self):
        return self._image_url(self.header, ssl=False)

    @amo.cached_property
    def footer_url(self):
        return self._image_url(self.footer, ssl=False)

    @amo.cached_property
    def update_url(self):
        return settings.PERSONAS_UPDATE_URL % self.persona_id

    @amo.cached_property
    def json_data(self):
        """Persona JSON Data for Browser/extension preview."""
        hexcolor = lambda color: '#%s' % color
        addon = self.addon
        return json.dumps({
            'id': unicode(self.persona_id),  # Personas dislikes ints
            'name': addon.name,
            'accentcolor': hexcolor(self.accentcolor),
            'textcolor': hexcolor(self.textcolor),
            'category': (addon.all_categories[0].name if
                         addon.all_categories else ''),
            'author': self.author,
            'description': addon.description,
            'header': self.header_url,
            'footer': self.footer_url,
            'headerURL': self.header_url,
            'footerURL': self.footer_url,
            'previewURL': self.thumb_url,
            'iconURL': self.icon_url,
            'updateURL': self.update_url,
        }, separators=(',', ':'), cls=JSONEncoder)

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


class Category(amo.models.ModelBase):
    name = TranslatedField()
    slug = models.SlugField(max_length=50, help_text='Used in Category URLs.')
    type = models.PositiveIntegerField(db_column='addontype_id',
                                       choices=do_dictsort(amo.ADDON_TYPE))
    application = models.ForeignKey('applications.Application', null=True,
                                    blank=True)
    count = models.IntegerField('Addon count', default=0)
    weight = models.IntegerField(
        default=0, help_text='Category weight used in sort ordering')
    misc = models.BooleanField(default=False)

    addons = models.ManyToManyField(Addon, through='AddonCategory')

    # Used for operator shelves and magic categories.
    carrier = models.PositiveIntegerField(
        choices=mkt.constants.CARRIER_IDS, null=True)
    region = models.PositiveIntegerField(
        choices=mkt.constants.REGIONS_CHOICES_ID, null=True)

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
        if settings.MARKETPLACE and self.type == amo.ADDON_PERSONA:
            #TODO: (davor) this is a temp stub. Return category URL when done.
            return reverse('themes.browse', args=[self.slug])
        return reverse('browse.%s' % type, args=[self.slug])

    @staticmethod
    def transformer(addons):
        qs = (Category.uncached.filter(addons__in=addons)
              .extra(select={'addon_id': 'addons_categories.addon_id'}))
        cats = dict((addon_id, list(cs))
                    for addon_id, cs in sorted_groupby(qs, 'addon_id'))
        for addon in addons:
            addon.all_categories = cats.get(addon.id, [])


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


class Flag(amo.models.ModelBase):
    addon = models.OneToOneField(Addon)
    adult_content = models.BooleanField(default=False, db_index=True)
    child_content = models.BooleanField(default=False, db_index=True)

    class Meta:
        db_table = 'flags'

    def __unicode__(self):
        return u"%s flags" % self.addon.name


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
    url = models.URLField(verify_exists=False)
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


# webapps.models imports addons.models to get Addon, so we need to keep the
# Webapp import down here.
from mkt.webapps.models import Webapp
