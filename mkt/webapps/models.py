# -*- coding: utf-8 -*-
import datetime
import json
import os
import time
import urlparse
import uuid

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django.core.urlresolvers import NoReverseMatch
from django.db import models
from django.dispatch import receiver
from django.utils.http import urlquote

import commonware.log
from elasticutils.contrib.django import F, S
from tower import ugettext as _

import amo
import amo.models
from access.acl import action_allowed, check_reviewer
from addons import query
from addons.models import (Addon, AddonDeviceType, Category,
                           update_search_index)
from addons.signals import version_changed
from amo.decorators import skip_cache
from amo.helpers import absolutify
from amo.storage_utils import copy_stored_file
from amo.urlresolvers import reverse
from amo.utils import JSONEncoder, smart_path
from constants.applications import DEVICE_TYPES
from files.models import File, nfd_str, Platform
from files.utils import parse_addon, WebAppParser
from lib.crypto import packaged
from versions.models import Version
from mkt.zadmin.models import FeaturedApp

import mkt
from mkt.constants import apps
from mkt.constants import APP_IMAGE_SIZES
from mkt.webapps.utils import get_locale_properties


log = commonware.log.getLogger('z.addons')


class WebappManager(amo.models.ManagerBase):

    def __init__(self, include_deleted=False):
        amo.models.ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_query_set(self):
        qs = super(WebappManager, self).get_query_set()
        qs = qs._clone(klass=query.IndexQuerySet).filter(
            type=amo.ADDON_WEBAPP)
        if not self.include_deleted:
            qs = qs.exclude(status=amo.STATUS_DELETED)
        return qs.transform(Webapp.transformer)

    def valid(self):
        return self.filter(status__in=amo.LISTED_STATUSES,
                           disabled_by_user=False)

    def reviewed(self):
        return self.filter(status__in=amo.REVIEWED_STATUSES)

    def visible(self):
        return self.filter(status=amo.STATUS_PUBLIC, disabled_by_user=False)

    def top_free(self, listed=True):
        qs = self.visible() if listed else self
        return (qs.filter(premium_type__in=amo.ADDON_FREES)
                .exclude(addonpremium__price__price__isnull=False)
                .order_by('-weekly_downloads')
                .with_index(addons='downloads_type_idx'))

    def top_paid(self, listed=True):
        qs = self.visible() if listed else self
        return (qs.filter(premium_type__in=amo.ADDON_PREMIUMS,
                          addonpremium__price__price__gt=0)
                .order_by('-weekly_downloads')
                .with_index(addons='downloads_type_idx'))

    @skip_cache
    def pending(self):
        # - Holding
        # ** Approved   -- PUBLIC
        # ** Unapproved -- PENDING
        # - Open
        # ** Reviewed   -- PUBLIC
        # ** Unreviewed -- LITE
        # ** Rejected   -- REJECTED
        return self.filter(status=amo.WEBAPPS_UNREVIEWED_STATUS)


# We use super(Addon, self) on purpose to override expectations in Addon that
# are not true for Webapp. Webapp is just inheriting so it can share the db
# table.
class Webapp(Addon):

    objects = WebappManager()
    with_deleted = WebappManager(include_deleted=True)

    class Meta:
        proxy = True

    def save(self, **kw):
        # Make sure we have the right type.
        self.type = amo.ADDON_WEBAPP
        self.clean_slug(slug_field='app_slug')
        self.assign_uuid()
        creating = not self.id
        super(Addon, self).save(**kw)
        if creating:
            # Set the slug once we have an id to keep things in order.
            self.update(slug='app-%s' % self.id)

    @staticmethod
    def transformer(apps):
        # I think we can do less than the Addon transformer, so at some point
        # we'll want to copy that over.
        apps_dict = Addon.transformer(apps)
        if not apps_dict:
            return

        for adt in AddonDeviceType.objects.filter(addon__in=apps_dict):
            if not getattr(apps_dict[adt.addon_id], '_device_types', None):
                apps_dict[adt.addon_id]._device_types = []
            apps_dict[adt.addon_id]._device_types.append(
                DEVICE_TYPES[adt.device_type])

    @staticmethod
    def version_and_file_transformer(apps):
        """Attach all the versions and files to the apps."""
        if not apps:
            return []

        ids = set(app.id for app in apps)
        versions = (Version.uncached.filter(addon__in=ids)
                                    .select_related('addon'))
        vids = [v.id for v in versions]
        files = (File.uncached.filter(version__in=vids)
                              .select_related('version'))

        # Attach the files to the versions.
        f_dict = dict((k, list(vs)) for k, vs in
                      amo.utils.sorted_groupby(files, 'version_id'))
        for version in versions:
            version.all_files = f_dict.get(version.id, [])
        # Attach the versions to the apps.
        v_dict = dict((k, list(vs)) for k, vs in
                      amo.utils.sorted_groupby(versions, 'addon_id'))
        for app in apps:
            app.all_versions = v_dict.get(app.id, [])

        return apps

    def get_url_path(self, more=False, add_prefix=True):
        # We won't have to do this when Marketplace absorbs all apps views,
        # but for now pretend you didn't see this.
        try:
            return reverse('detail', args=[self.app_slug],
                           add_prefix=add_prefix)
        except NoReverseMatch:
            # Fall back to old details page until the views get ported.
            return super(Webapp, self).get_url_path(more=more,
                                                    add_prefix=add_prefix)

    def get_detail_url(self, action=None):
        """Reverse URLs for 'detail', 'details.record', etc."""
        return reverse(('detail.%s' % action) if action else 'detail',
                       args=[self.app_slug])

    def get_purchase_url(self, action=None, args=None):
        """Reverse URLs for 'purchase', 'purchase.done', etc."""
        return reverse(('purchase.%s' % action) if action else 'purchase',
                       args=[self.app_slug] + (args or []))

    def get_dev_url(self, action='edit', args=None, prefix_only=False):
        # Either link to the "new" Marketplace Developer Hub or the old one.
        args = args or []
        prefix = ('mkt.developers' if getattr(settings, 'MARKETPLACE', False)
                  else 'devhub')
        view_name = ('%s.%s' if prefix_only else '%s.apps.%s')
        return reverse(view_name % (prefix, action),
                       args=[self.app_slug] + args)

    def get_ratings_url(self, action='list', args=None, add_prefix=True):
        """Reverse URLs for 'ratings.list', 'ratings.add', etc."""
        return reverse(('ratings.%s' % action),
                       args=[self.app_slug] + (args or []),
                       add_prefix=add_prefix)

    def get_stats_url(self, action='overview', inapp='', args=None):
        """Reverse URLs for 'stats', 'stats.overview', etc."""
        # Simplifies the templates to not have to choose whether to call
        # get_stats_url or get_stats_inapp_url.
        if inapp:
            stats_url = self.get_stats_inapp_url(action=action,
                                                 inapp=inapp, args=args)
            return stats_url
        if action.endswith('_inapp'):
            action = action.replace('_inapp', '')
        return reverse(('mkt.stats.%s' % action),
                       args=[self.app_slug] + (args or []))

    def get_stats_inapp_url(self, action='revenue', inapp='', args=None):
        """
        Inapp reverse URLs for stats.
        """
        if not action.endswith('_inapp'):
            action += '_inapp'
        try:
            url = reverse(('mkt.stats.%s' % action),
                          args=[self.app_slug, urlquote(inapp)])
        except NoReverseMatch:
            url = reverse(('mkt.stats.%s' % 'revenue_inapp'),
                          args=[self.app_slug, urlquote(inapp)])
        return url

    def get_image_asset_url(self, slug, default=64):
        """
        Returns the URL for an app's image asset that uses the slug specified
        by `slug`.
        """
        if not any(slug == x['slug'] for x in APP_IMAGE_SIZES):
            raise Exception(
                "Requesting image asset for size that doesn't exist.")

        try:
            return ImageAsset.objects.get(addon=self, slug=slug).image_url
        except ImageAsset.DoesNotExist:
            return settings.MEDIA_URL + 'img/hub/default-%s.png' % str(default)

    def get_image_asset_hue(self, slug):
        """
        Returns the URL for an app's image asset that uses the slug specified
        by `slug`.
        """
        if not any(slug == x['slug'] for x in APP_IMAGE_SIZES):
            raise Exception(
                "Requesting image asset for size that doesn't exist.")

        try:
            return ImageAsset.objects.get(addon=self, slug=slug).hue
        except ImageAsset.DoesNotExist:
            return 0

    @staticmethod
    def domain_from_url(url):
        if not url:
            raise ValueError('URL was empty')
        pieces = urlparse.urlparse(url)
        return '%s://%s' % (pieces.scheme, pieces.netloc.lower())

    @property
    def parsed_app_domain(self):
        if self.is_packaged:
            raise ValueError('Packaged apps do not have a domain')
        return urlparse.urlparse(self.app_domain)

    @property
    def device_types(self):
        # If the transformer attached something, use it.
        if hasattr(self, '_device_types'):
            return self._device_types
        return [DEVICE_TYPES[d.device_type] for d in
                self.addondevicetype_set.order_by('device_type')]

    @property
    def origin(self):
        parsed = urlparse.urlparse(self.get_manifest_url())
        return '%s://%s' % (parsed.scheme, parsed.netloc)

    def get_manifest_url(self, reviewer=False):
        """
        Hosted apps: a URI to an external manifest.
        Packaged apps: a URI to a mini manifest on m.m.o. If reviewer, the
        mini-manifest behind reviewer auth pointing to the reviewer-signed
        package.
        """
        if self.is_packaged:
            if reviewer:
                # Get latest version and return reviewer manifest URL.
                version = self.versions.latest()
                return absolutify(reverse('reviewers.mini_manifest',
                                          args=[self.id, version.id]))
            elif self.current_version:
                return absolutify(reverse('detail.manifest', args=[self.guid]))
            else:
                return ''  # No valid version.
        else:
            return self.manifest_url

    def has_icon_in_manifest(self):
        data = self.get_manifest_json()
        return 'icons' in data

    def get_manifest_json(self, file_obj=None):
        file_ = file_obj or self.get_latest_file()
        if not file_:
            return
        if self.status == amo.STATUS_REJECTED:
            file_path = file_.guarded_file_path
        else:
            file_path = file_.file_path

        return WebAppParser().get_json_data(file_path)

    def share_url(self):
        return reverse('apps.share', args=[self.app_slug])

    def manifest_updated(self, manifest, upload):
        """The manifest has updated, update the version and file.

        This is intended to be used for hosted apps only, which have only a
        single version and a single file.
        """
        data = parse_addon(upload, self)
        version = self.versions.latest()
        version.update(version=data['version'])
        path = smart_path(nfd_str(upload.path))
        file = version.files.latest()
        file.filename = file.generate_filename(extension='.webapp')
        file.size = storage.size(path)
        file.hash = file.generate_hash(path)
        log.info('Updated file hash to %s' % file.hash)
        file.save()

        # Move the uploaded file from the temp location.
        copy_stored_file(path, os.path.join(version.path_prefix,
                                            nfd_str(file.filename)))
        log.info('[Webapp:%s] Copied updated manifest to %s' % (
            self, version.path_prefix))

        amo.log(amo.LOG.MANIFEST_UPDATED, self)

    def is_complete(self):
        """See if the app is complete. If not, return why. This function does
        not consider or include payments-related information.

        """

        reasons = []

        if not self.support_email:
            reasons.append(_('You must provide a support email.'))
        if not self.name:
            reasons.append(_('You must provide an app name.'))
        if not self.device_types:
            reasons.append(_('You must provide at least one device type.'))

        if not self.categories.count():
            reasons.append(_('You must provide at least one category.'))
        if not self.previews.count():
            reasons.append(_('You must upload at least one screenshot or '
                             'video.'))

        return not bool(reasons), reasons

    def mark_done(self):
        """When the submission process is done, update status accordingly."""
        self.update(status=amo.WEBAPPS_UNREVIEWED_STATUS)

    def update_status(self, using=None):
        if (self.is_deleted or self.is_disabled or
            self.status == amo.STATUS_BLOCKED):
            return

        def _log(reason, old=self.status):
            log.info(u'Update app status [%s]: %s => %s (%s).' % (
                self.id, old, self.status, reason))
            amo.log(amo.LOG.CHANGE_STATUS, self.get_status_display(), self)

        # Handle the case of no versions.
        if not self.versions.exists():
            self.update(status=amo.STATUS_NULL)
            _log('no versions')
            return

        # Handle the case of versions with no files.
        if not self.versions.filter(files__isnull=False).exists():
            self.update(status=amo.STATUS_NULL)
            _log('no versions with files')
            return

        # If there are no public versions and at least one pending, set status
        # to pending.
        has_public = (
            self.versions.filter(files__status=amo.STATUS_PUBLIC).exists())
        has_pending = (
            self.versions.filter(files__status=amo.STATUS_PENDING).exists())
        if not has_public and has_pending:
            self.update(status=amo.STATUS_PENDING)
            _log('has pending but no public files')
            return

    def authors_other_addons(self, app=None):
        """Return other apps by the same author."""
        return (self.__class__.objects.visible()
                              .filter(type=amo.ADDON_WEBAPP)
                              .exclude(id=self.id).distinct()
                              .filter(addonuser__listed=True,
                                      authors__in=self.listed_authors))

    def can_purchase(self):
        return self.is_premium() and self.premium and self.is_public()

    def is_purchased(self, user):
        return user and self.id in user.purchase_ids()

    def is_pending(self):
        return self.status == amo.STATUS_PENDING

    def is_visible(self, request):
        """Returns whether the app has a visible search result listing. Its
        detail page will always be there.

        This does not consider whether an app is excluded in the current region
        by the developer.
        """

        region = getattr(request, 'REGION', mkt.regions.WORLDWIDE)

        # See if it's a game without a content rating.
        if (region == mkt.regions.BR and self.listed_in(category='games') and
            not self.content_ratings_in(mkt.regions.BR, 'games')):
            unrated_brazil_game = True
        else:
            unrated_brazil_game = False

        # Let developers see it always.
        can_see = (self.has_author(request.amo_user) or
                   action_allowed(request, 'Apps', 'Edit'))

        # Let app reviewers see it only when it's pending.
        if check_reviewer(request, only='app') and self.is_pending():
            can_see = True

        visible = False

        if can_see:
            # Developers and reviewers should see it always.
            visible = True
        elif self.is_public() and not unrated_brazil_game:
            # Everyone else can see it only if it's public -
            # and if it's a game, it must have a content rating.
            visible = True

        return visible

    def has_price(self):
        """
        If the app is premium and has a price greater than zero. Primarily
        of use in the payment flow to determine if we need payment. An app can
        be premium, but not require any payment.
        """
        return bool(self.is_premium() and self.premium and
                    self.premium.has_price())

    def get_price(self):
        if self.has_price():
            return self.premium.get_price_locale()
        return _(u'Free')

    @amo.cached_property
    def promo(self):
        return self.get_promo()

    def get_promo(self):
        try:
            return self.previews.filter(position=-1)[0]
        except IndexError:
            pass

    def get_region_ids(self, worldwide=False):
        """Return IDs of regions in which this app is listed."""
        if worldwide:
            all_ids = mkt.regions.ALL_REGION_IDS
        else:
            all_ids = mkt.regions.REGION_IDS
        excluded = list(self.addonexcludedregion
                            .values_list('region', flat=True))
        return sorted(list(set(all_ids) - set(excluded)))

    def get_regions(self):
        """
        Return regions, e.g.:
            [<class 'mkt.constants.regions.BR'>,
             <class 'mkt.constants.regions.CA'>,
             <class 'mkt.constants.regions.UK'>,
             <class 'mkt.constants.regions.US'>,
             <class 'mkt.constants.regions.WORLDWIDE'>]
        """
        regions = map(mkt.regions.REGIONS_CHOICES_ID_DICT.get,
                      self.get_region_ids(worldwide=True))
        return sorted(regions, key=lambda x: x.slug)

    def listed_in(self, region=None, category=None):
        listed = []
        if region:
            listed.append(region.id in self.get_region_ids(worldwide=True))
        if category:
            if isinstance(category, basestring):
                filters = {'slug': category}
            else:
                filters = {'id': category.id}
            listed.append(self.category_set.filter(**filters).exists())
        return all(listed or [False])

    def content_ratings_in(self, region, category=None):
        """Give me the content ratings for a game listed in Brazil."""

        # If we want to find games in Brazil with content ratings, then
        # make sure it's actually listed in Brazil and it's a game.
        if category and not self.listed_in(region, category):
            return []

        rb = [x.id for x in region.ratingsbodies]
        return list(self.content_ratings.filter(ratings_body__in=rb)
                        .order_by('rating'))

    @classmethod
    def now(cls):
        return datetime.date.today()

    @classmethod
    def featured(cls, cat=None, region=None, limit=9, mobile=False,
                 gaia=False):
        qs = FeaturedApp.objects.featured(cat, region, limit, mobile, gaia)
        return [w.app for w in qs]

    @classmethod
    def get_excluded_in(cls, region):
        """Return IDs of Webapp objects excluded from a particular region."""
        return list(AddonExcludedRegion.objects.filter(region=region.id)
                    .values_list('addon', flat=True))

    @classmethod
    def from_search(cls, cat=None, region=None, gaia=False, mobile=False,
                    tablet=False, status=amo.STATUS_PUBLIC):
        filters = dict(type=amo.ADDON_WEBAPP, status=status, is_disabled=False)

        if cat:
            filters.update(category=cat.id)

        srch = S(cls).query(**filters)
        if region:
            excluded = cls.get_excluded_in(region)
            if excluded:
                srch = srch.filter(~F(id__in=excluded))

        if mobile:
            srch = srch.filter(uses_flash=False)

        if (mobile or tablet) and not gaia:
            # Don't show packaged apps on Firefox for Android.
            srch = srch.filter(is_packaged=False)

            # Only show premium apps on gaia and desktop for now.
            srch = srch.filter(~F(premium_type__in=amo.ADDON_PREMIUMS,
                               price__gt=0))

        return srch

    @classmethod
    def popular(cls, cat=None, region=None, gaia=False):
        """Elastically grab the most popular apps."""
        return cls.from_search(cat, region, gaia=gaia).order_by('-popularity')

    @classmethod
    def latest(cls, cat=None, region=None, gaia=False):
        """Elastically grab the most recent apps."""
        return cls.from_search(cat, region, gaia=gaia).order_by('-created')

    @classmethod
    def category(cls, slug):
        try:
            return (Category.objects
                    .filter(type=amo.ADDON_WEBAPP, slug=slug))[0]
        except IndexError:
            return None

    def in_rereview_queue(self):
        return self.rereviewqueue_set.exists()

    def get_cached_manifest(self, force=False):
        """
        Creates the "mini" manifest for packaged apps and caches it.

        Call this with `force=True` whenever we need to update the cached
        version of this manifest, e.g., when a new version of the packaged app
        is approved.

        If the addon is not a packaged app, this will not cache anything.

        """
        if not self.is_packaged:
            return

        key = 'webapp:{0}:manifest'.format(self.pk)

        if not force:
            data = cache.get(key)
            if data:
                return data

        version = self.current_version
        if not version:
            data = {}
        else:
            file_obj = version.all_files[0]
            manifest = self.get_manifest_json()
            package_path = absolutify(
                os.path.join(reverse('downloads.file', args=[file_obj.id]),
                             file_obj.filename))

            data = {
                'name': manifest['name'],
                'version': version.version,
                'size': storage.size(file_obj.signed_file_path),
                'release_notes': version.releasenotes,
                'package_path': package_path,
            }
            for key in ['developer', 'icons', 'locales']:
                if key in manifest:
                    data[key] = manifest[key]

        data = json.dumps(data, cls=JSONEncoder)

        cache.set(key, data, 0)

        return data

    def sign_if_packaged(self, version_pk, reviewer=False):
        if not self.is_packaged:
            return
        return packaged.sign(version_pk, reviewer=reviewer)

    def assign_uuid(self):
        """Generates a UUID if self.guid is not already set."""
        if not self.guid:
            max_tries = 10
            tried = 1
            guid = str(uuid.uuid4())
            while tried <= max_tries:
                if not Webapp.objects.filter(guid=guid).exists():
                    self.guid = guid
                    break
                else:
                    guid = str(uuid.uuid4())
                    tried += 1
            else:
                raise ValueError('Could not auto-generate a unique UUID')

    def is_premium_type_upgrade(self, premium_type):
        """
        Returns True if changing self.premium_type from current value to passed
        in value is considered an upgrade that should trigger a re-review.
        """
        ALL = set(amo.ADDON_FREES + amo.ADDON_PREMIUMS)
        free_upgrade = ALL - set([amo.ADDON_FREE])
        free_inapp_upgrade = ALL - set([amo.ADDON_FREE, amo.ADDON_FREE_INAPP])

        if (self.premium_type == amo.ADDON_FREE and
            premium_type in free_upgrade):
            return True
        if (self.premium_type == amo.ADDON_FREE_INAPP and
            premium_type in free_inapp_upgrade):
            return True
        return False

    def create_blocklisted_version(self):
        """
        Creates a new version who's file is the blocklisted app found in /media
        and sets status to STATUS_BLOCKLISTED.

        """
        blocklisted_path = os.path.join(settings.MEDIA_ROOT, 'packaged-apps',
                                        'blocklisted.zip')
        last_version = self.current_version.version
        v = Version.objects.create(
            addon=self, version='blocklisted-%s' % last_version)
        f = File(version=v, status=amo.STATUS_BLOCKED,
                 platform=Platform.objects.get(id=amo.PLATFORM_ALL.id))
        f.filename = f.generate_filename()
        copy_stored_file(blocklisted_path, f.file_path)
        log.info(u'[Webapp:%s] Copied blocklisted app from %s to %s' % (
            self.id, blocklisted_path, f.file_path))
        f.size = storage.size(f.file_path)
        f.hash = f.generate_hash(f.file_path)
        f.save()
        f.inject_ids()
        self.sign_if_packaged(v.pk)
        self.status = amo.STATUS_BLOCKED
        self._current_version = v
        self.save()

    def update_name_from_package_manifest(self):
        """
        Looks at the manifest.webapp inside the current version's file and
        updates the app's name and translated names.

        Note: Make sure the correct version is in place before calling this.
        """
        if not self.is_packaged:
            return None

        file_ = self.versions.latest().all_files[0]
        mf = self.get_manifest_json(file_)

        # Get names in "locales" as {locale: name}.
        locale_names = get_locale_properties(mf, 'name', self.default_locale)

        # Check changes to default_locale.
        locale_changed = self.update_default_locale(mf.get('default_locale'))
        if locale_changed:
            log.info(u'[Webapp:%s] Default locale changed from "%s" to "%s".'
                     % (self.pk, locale_changed[0], locale_changed[1]))

        # Update names
        crud = self.update_names(locale_names)
        if any(crud.values()):
            self.save()

    @property
    def app_type(self):
        # Returns string of 'hosted' or 'packaged'. Used in the API.
        key = (amo.ADDON_WEBAPP_PACKAGED if self.is_packaged else
               amo.ADDON_WEBAPP_HOSTED)
        return amo.ADDON_WEBAPP_TYPES[key]


# Pull all translated_fields from Addon over to Webapp.
Webapp._meta.translated_fields = Addon._meta.translated_fields


models.signals.post_save.connect(update_search_index, sender=Webapp,
                                 dispatch_uid='mkt.webapps.index')


@receiver(version_changed, dispatch_uid='update_cached_manifests')
def update_cached_manifests(sender, **kw):
    if not kw.get('raw'):
        from mkt.webapps.tasks import update_cached_manifests
        update_cached_manifests.delay(sender.id)


class ImageAsset(amo.models.ModelBase):
    addon = models.ForeignKey(Addon, related_name='image_assets')
    filetype = models.CharField(max_length=25, default='image/png')
    slug = models.CharField(max_length=25)
    hue = models.PositiveIntegerField(null=False, default=0)

    class Meta:
        db_table = 'image_assets'

    def flush_urls(self):
        return ['*/addon/%d/' % self.addon_id, self.image_url, ]

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

    @property
    def file_extension(self):
        # Assume that blank is an image.
        return 'png' if not self.filetype else self.filetype.split('/')[1]

    @property
    def image_url(self):
        return self._image_url(settings.IMAGEASSET_FULL_URL)

    @property
    def image_path(self):
        return self._image_path(settings.IMAGEASSET_FULL_PATH)


class Installed(amo.models.ModelBase):
    """Track WebApp installations."""
    addon = models.ForeignKey('addons.Addon', related_name='installed')
    user = models.ForeignKey('users.UserProfile')
    uuid = models.CharField(max_length=255, db_index=True, unique=True)
    client_data = models.ForeignKey('stats.ClientData', null=True)
    # Because the addon could change between free and premium,
    # we need to store the state at time of install here.
    premium_type = models.PositiveIntegerField(
        null=True, default=None, choices=amo.ADDON_PREMIUM_TYPES.items())
    install_type = models.PositiveIntegerField(
        db_index=True, default=apps.INSTALL_TYPE_USER,
        choices=apps.INSTALL_TYPES.items())

    class Meta:
        db_table = 'users_install'
        unique_together = ('addon', 'user', 'install_type', 'client_data')


@receiver(models.signals.post_save, sender=Installed)
def add_uuid(sender, **kw):
    if not kw.get('raw'):
        install = kw['instance']
        if not install.uuid and install.premium_type is None:
            install.uuid = ('%s-%s' % (install.pk, str(uuid.uuid4())))
            install.premium_type = install.addon.premium_type
            install.save()


class AddonExcludedRegion(amo.models.ModelBase):
    """
    Apps are listed in all regions by default.
    When regions are unchecked, we remember those excluded regions.
    """
    addon = models.ForeignKey('addons.Addon',
                              related_name='addonexcludedregion')
    region = models.PositiveIntegerField(
        choices=mkt.regions.REGIONS_CHOICES_ID)

    class Meta:
        db_table = 'addons_excluded_regions'
        unique_together = ('addon', 'region')

    def __unicode__(self):
        region = self.get_region()
        return u'%s: %s' % (self.addon, region.slug if region else None)

    def get_region(self):
        return mkt.regions.REGIONS_CHOICES_ID_DICT.get(self.region)


class ContentRating(amo.models.ModelBase):
    """
    Ratings body information about an app.
    """
    addon = models.ForeignKey('addons.Addon', related_name='content_ratings')
    ratings_body = models.PositiveIntegerField(
        choices=[(k, rb.name) for k, rb in
                 mkt.ratingsbodies.RATINGS_BODIES.items()],
        null=False)
    rating = models.PositiveIntegerField(null=False)

    def __unicode__(self):
        return u'%s: %s' % (self.addon, self.get_label())

    def get_body(self):
        """Gives us something like DEJUS."""
        return mkt.ratingsbodies.RATINGS_BODIES[self.ratings_body]

    def get_rating(self):
        """Gives us the rating class (containing the name and description)."""
        return self.get_body().ratings[self.rating]

    def get_label(self):
        """Gives us the name to be used for the form options."""
        return u'%s - %s' % (self.get_body().name, self.get_rating().name)
