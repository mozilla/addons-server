# -*- coding: utf-8 -*-
import json
import os
import urlparse
import uuid

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.urlresolvers import NoReverseMatch
from django.db import models
from django.dispatch import receiver
from django.utils.http import urlquote

import commonware.log
import waffle
from tower import ugettext as _

import amo
import amo.models
import amo.utils
from addons import query
from addons.models import (Addon, AddonDeviceType, update_name_table,
                           update_search_index)
from amo.decorators import skip_cache
from amo.storage_utils import copy_stored_file
from amo.urlresolvers import reverse
from constants.applications import DEVICE_TYPES
from files.models import nfd_str
from files.utils import parse_addon

import mkt
from mkt.constants import ratingsbodies

log = commonware.log.getLogger('z.addons')


class WebappManager(amo.models.ManagerBase):

    def __init__(self, include_deleted=False):
        amo.models.ManagerBase.__init__(self)
        self.include_deleted = include_deleted

    def get_query_set(self):
        qs = super(WebappManager, self).get_query_set()
        qs = qs._clone(klass=query.IndexQuerySet).filter(type=amo.ADDON_WEBAPP)
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
        parsed = urlparse.urlparse(self.manifest_url)
        return '%s://%s' % (parsed.scheme, parsed.netloc)

    def get_latest_file(self):
        """Get the latest file from the current version."""
        cur = self.current_version
        if cur:
            res = cur.files.order_by('-created')
            if res:
                return res[0]

    def has_icon_in_manifest(self):
        data = self.get_manifest_json()
        return 'icons' in data

    def get_manifest_json(self):
        try:
            # The first file created for each version of the web app
            # is the manifest.
            with storage.open(self.get_latest_file().file_path, 'r') as mf:
                return json.load(mf)
        except Exception, e:
            log.error('Failed to open saved manifest %r for webapp %s, %s.'
                      % (self.manifest_url, self.pk, e))
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
        path = amo.utils.smart_path(nfd_str(upload.path))
        file = version.files.latest()
        file.filename = file.generate_filename(extension='.webapp')
        file.size = int(max(1, round(storage.size(path) / 1024, 0)))
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

    def has_price(self):
        return bool(self.is_premium() and self.premium and self.premium.price)

    def get_price(self):
        if self.is_premium() and self.premium:
            return self.premium.get_price_locale()
        return _(u'FREE')

    @amo.cached_property
    def promo(self):
        return self.get_promo()

    def get_promo(self):
        try:
            return self.previews.filter(position=-1)[0]
        except IndexError:
            pass

    def get_region_ids(self):
        """Return IDs of regions in which this app is listed."""
        excluded = list(self.addonexcludedregion
                            .values_list('region', flat=True))
        return list(set(mkt.regions.REGION_IDS) - set(excluded))

    def get_regions(self):
        """
        Return regions, e.g.:
            [<class 'mkt.constants.regions.BR'>,
             <class 'mkt.constants.regions.CA'>,
             <class 'mkt.constants.regions.UK'>,
             <class 'mkt.constants.regions.US'>]
        """
        regions = filter(None, [mkt.regions.REGIONS_CHOICES_ID_DICT.get(r)
                                for r in self.get_region_ids()])
        return sorted(regions, key=lambda x: x.slug)

    @classmethod
    def featured(cls, cat=None, region=None, limit=6):
        FeaturedApp = models.get_model('zadmin', 'FeaturedApp')
        qs = (FeaturedApp.objects
              .filter(app__status=amo.STATUS_PUBLIC,
                      app__disabled_by_user=False)
              .order_by('-app__weekly_downloads'))
        if isinstance(cat, list):
            qs = qs.filter(category__in=cat)
        else:
            qs = qs.filter(category=cat)
        if region:
            qs = qs.filter(regions__region=region.id)
        if limit:
            qs = qs[:limit]
        return [fa.app for fa in qs]

    @classmethod
    def from_search(cls):
        return cls.search().filter(type=amo.ADDON_WEBAPP,
                                   status=amo.STATUS_PUBLIC,
                                   is_disabled=False)

    @classmethod
    def popular(cls):
        """Elastically grab the most popular apps."""
        return cls.from_search().order_by('-weekly_downloads')

    @classmethod
    def latest(cls):
        """Elastically grab the most recent apps."""
        return cls.from_search().order_by('-created')

    @property
    def uses_flash(self):
        """
        Convenience property until more sophisticated per-version
        checking is done for packaged apps.
        """
        return self.get_latest_file().uses_flash

    @amo.cached_property
    def has_packaged_files(self):
        """
        Whether this app has any versions that are a packaged app.
        """
        return self.versions.filter(files__is_packaged=True).exists()


# Pull all translated_fields from Addon over to Webapp.
Webapp._meta.translated_fields = Addon._meta.translated_fields


models.signals.post_save.connect(update_search_index, sender=Webapp,
                                 dispatch_uid='mkt.webapps.index')
models.signals.post_save.connect(update_name_table, sender=Webapp,
                                 dispatch_uid='mkt.webapps.update.name.table')


class Installed(amo.models.ModelBase):
    """Track WebApp installations."""
    addon = models.ForeignKey('addons.Addon', related_name='installed')
    user = models.ForeignKey('users.UserProfile')
    uuid = models.CharField(max_length=255, db_index=True, unique=True)
    client_data = models.ForeignKey('stats.ClientData', null=True)
    # Because the addon could change between free and premium,
    # we need to store the state at time of install here.
    premium_type = models.PositiveIntegerField(null=True, default=None,
        choices=amo.ADDON_PREMIUM_TYPES.items())

    class Meta:
        db_table = 'users_install'
        unique_together = ('addon', 'user', 'client_data')


@receiver(models.signals.post_save, sender=Installed)
def add_uuid(sender, **kw):
    if not kw.get('raw'):
        install = kw['instance']
        if not install.uuid and install.premium_type == None:
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
        return u'%s: %s' % (self.addon.name, region.slug if region else None)

    def get_region(self):
        return mkt.regions.REGIONS_CHOICES_ID_DICT.get(self.region)


class ContentRating(amo.models.ModelBase):
    """
    Ratings body information about an app.
    """
    addon = models.ForeignKey('addons.Addon', related_name='content_ratings')
    ratings_body = models.PositiveIntegerField(
        choices=[(k, rb.name) for k, rb in
                 ratingsbodies.RATINGS_BODIES.items()],
        null=False)
    rating = models.PositiveIntegerField(null=False)

    def __unicode__(self):
        rb = ratingsbodies.RATINGS_BODIES[self.ratings_body]
        return '%s - %s' % (rb.name,
                            rb.ratings[self.rating].name)
