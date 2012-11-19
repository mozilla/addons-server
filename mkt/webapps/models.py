# -*- coding: utf-8 -*-
import datetime
import json
import os
import time
import urlparse
import uuid
import zipfile

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django.core.urlresolvers import NoReverseMatch
from django.db import models
from django.dispatch import receiver
from django.utils.http import urlquote

import commonware.log
import waffle
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
from files.models import File, nfd_str
from files.utils import parse_addon
from lib.crypto import packaged
from versions.models import Version

import mkt
from mkt.constants import APP_IMAGE_SIZES
from mkt.carriers import get_carrier


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
            return

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

    def get_manifest_url(self):
        """
        Hosted apps: a URI to an external manifest.
        Packaged apps: a URI to a mini manifest on m.m.o.
        """
        if self.is_packaged:
            if self.current_version:
                return absolutify(self.get_detail_url('manifest'))
            else:
                # Invalid statuses don't have `current_version`.
                # TODO: Ask Rob about reviewers being able to install
                # disabled apps?
                return ''
        else:
            return self.manifest_url

    def has_icon_in_manifest(self):
        data = self.get_manifest_json()
        return 'icons' in data

    def get_manifest_json(self, file_obj=None):
        file_ = file_obj or self.get_latest_file()
        if not file_:
            return

        file_path = file_.file_path
        try:
            if zipfile.is_zipfile(file_path):
                zf = zipfile.ZipFile(file_path)
                data = zf.open('manifest.webapp').read()
                zf.close()
                return json.loads(data)
            else:
                file = storage.open(file_path, 'r')
                data = file.read()
                return json.loads(data)

        except Exception, e:
            log.error(u'[Webapp:%s] Failed to open saved file %r, %s.'
                      % (self, file_path, e))
            raise

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
        file.hash = (file.generate_hash(path) if
                     waffle.switch_is_active('file-hash-paranoia') else
                     upload.hash)
        log.info('Updated file hash to %s' % file.hash)
        file.save()

        # Move the uploaded file from the temp location.
        copy_stored_file(path, os.path.join(version.path_prefix,
                                            nfd_str(file.filename)))
        log.info('[Webapp:%s] Copied updated manifest to %s' % (
            self, version.path_prefix))

        amo.log(amo.LOG.MANIFEST_UPDATED, self)

    def is_complete(self):
        """See if the app is complete. If not, return why."""
        reasons = []
        if self.needs_paypal():
            if not self.paypal_id:
                reasons.append(_('You must set up payments.'))
            if not self.has_price():
                reasons.append(_('You must specify a price.'))

        if not self.support_email:
            reasons.append(_('You must provide a support email.'))
        if not self.name:
            reasons.append(_('You must provide an app name.'))
        if not self.device_types:
            reasons.append(_('You must provide at least one device type.'))

        if not self.categories.count():
            reasons.append(_('You must provide at least one category.'))
        if not self.previews.count():
            reasons.append(_('You must upload at least one '
                             'screenshot or video.'))

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
        return bool(self.is_premium() and self.premium and self.premium.price)

    def get_price(self):
        if self.is_premium() and self.premium:
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
        return list(set(all_ids) - set(excluded))

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
    def featured(cls, cat=None, region=None, limit=6, mobile=False,
                 gaia=False):
        FeaturedApp = models.get_model('zadmin', 'FeaturedApp')
        qs = (FeaturedApp.objects
              .filter(app__status=amo.STATUS_PUBLIC,
                      app__disabled_by_user=False)
              .order_by('-app__weekly_downloads'))
        qs = (qs.filter(start_date__lte=cls.now())
              | qs.filter(start_date__isnull=True))
        qs = (qs.filter(end_date__gte=cls.now())
              | qs.filter(end_date__isnull=True))

        if waffle.switch_is_active('disabled-payments') or not gaia:
            qs = qs.filter(app__premium_type__in=amo.ADDON_FREES)

        if isinstance(cat, list):
            qs = qs.filter(category__in=cat)
        else:
            qs = qs.filter(category=cat.id if cat else None)

        locale_qs = FeaturedApp.objects.none()
        worldwide_qs = FeaturedApp.objects.none()

        carrier = get_carrier()
        if carrier:
            qs = qs.filter(carriers__carrier=carrier)

        if gaia:
            qs = qs.filter(
                app__addondevicetype__device_type=amo.DEVICE_GAIA.id)
        elif mobile:
            qs = qs.filter(
                app__addondevicetype__device_type=amo.DEVICE_MOBILE.id)

        if region:
            excluded = cls.get_excluded_in(region)
            locale_qs = (qs.filter(regions__region=region.id)
                         .exclude(app__id__in=excluded))

            # Fill the empty spots with Worldwide-featured apps.
            if limit:
                empty_spots = limit - locale_qs.count()
                if empty_spots > 0 and region != mkt.regions.WORLDWIDE:
                    ww = mkt.regions.WORLDWIDE.id
                    worldwide_qs = (qs.filter(regions__region=ww)
                                    .exclude(id__in=[x.id for x in locale_qs])
                                    .exclude(app__id__in=excluded))[:limit]

        if limit:
            locale_qs = locale_qs[:limit]

        if worldwide_qs:
            combined = ([fa.app for fa in locale_qs] +
                        [fa.app for fa in worldwide_qs])
            return list(set(combined))[:limit]

        return [fa.app for fa in locale_qs]

    @classmethod
    def get_excluded_in(cls, region):
        """Return IDs of Webapp objects excluded from a particular region."""
        return list(AddonExcludedRegion.objects.filter(region=region.id)
                    .values_list('addon', flat=True))

    @classmethod
    def from_search(cls, cat=None, region=None, gaia=False):
        filters = dict(type=amo.ADDON_WEBAPP,
                       status=amo.STATUS_PUBLIC,
                       is_disabled=False)

        if cat:
            filters.update(category=cat.id)

        srch = S(cls).query(**filters)
        if region:
            excluded = cls.get_excluded_in(region)
            if excluded:
                srch = srch.filter(~F(id__in=excluded))

        if waffle.switch_is_active('disabled-payments') or not gaia:
            srch = srch.filter(premium_type__in=amo.ADDON_FREES, price=0)

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
            file = version.all_files[0]
            manifest = self.get_manifest_json()

            data = {
                'name': self.name,
                'version': version.version,
                'size': file.size,
                'release_notes': version.releasenotes,
                'package_path': file.get_url_path('manifest'),
            }
            if 'icons' in manifest:
                data['icons'] = manifest['icons']
            if 'locales' in manifest:
                data['locales'] = manifest['locales']

        data = json.dumps(data, cls=JSONEncoder)

        cache.set(key, data, 0)

        return data

    def sign_if_packaged(self, version_pk, reviewer=False):
        if not self.is_packaged:
            return
        return packaged.sign(version_pk, reviewer=reviewer)


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

    class Meta:
        db_table = 'users_install'
        unique_together = ('addon', 'user', 'client_data')


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
