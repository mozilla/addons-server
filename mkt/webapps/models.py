# -*- coding: utf-8 -*-
import datetime
import hashlib
import json
import os
import urlparse
import uuid
from operator import attrgetter

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage as storage
from django.core.urlresolvers import NoReverseMatch
from django.db import models
from django.db.models import Min, Q, signals as dbsignals
from django.dispatch import receiver

import commonware.log
import json_field
import waffle
from elasticutils.contrib.django import F, Indexable, MappingType
from tower import ugettext as _

import amo
import amo.models
from access.acl import action_allowed, check_reviewer
from addons import query
from addons.models import (Addon, AddonDeviceType, AddonUpsell,
                           attach_categories, attach_devices, attach_prices,
                           attach_tags, attach_translations, Category)
from addons.signals import version_changed
from amo.decorators import skip_cache, write
from amo.helpers import absolutify
from amo.storage_utils import copy_stored_file
from amo.urlresolvers import reverse
from amo.utils import (JSONEncoder, memoize, memoize_key, smart_path,
                       to_language, urlparams)
from constants.applications import DEVICE_TYPES
from files.models import File, nfd_str, Platform
from files.utils import parse_addon, WebAppParser
from market.models import AddonPremium
from stats.models import ClientData
from translations.fields import PurifiedField, save_signal
from versions.models import Version

from lib.crypto import packaged
from lib.iarc.client import get_iarc_client
from lib.iarc.utils import (get_iarc_app_title, render_xml,
                            REVERSE_DESC_MAPPING, REVERSE_INTERACTIVES_MAPPING)

import mkt
from mkt.constants import APP_FEATURES, apps
from mkt.regions.utils import parse_region
from mkt.search.utils import S
from mkt.site.models import DynamicBoolFieldsMixin
from mkt.webapps.utils import (dehydrate_content_rating, dehydrate_descriptors,
                               dehydrate_interactives, get_locale_properties,
                               get_supported_locales)


log = commonware.log.getLogger('z.addons')


def reverse_version(version):
    """
    The try/except AttributeError allows this to be used where the input is
    ambiguous, and could be either an already-reversed URL or a Version object.
    """
    if version:
        try:
            return reverse('version-detail', kwargs={'pk': version.pk})
        except AttributeError:
            return version
    return


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
                .order_by('-weekly_downloads')
                .with_index(addons='downloads_type_idx'))

    def top_paid(self, listed=True):
        qs = self.visible() if listed else self
        return (qs.filter(premium_type__in=amo.ADDON_PREMIUMS)
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

    @skip_cache
    def pending_in_region(self, region):
        """
        Apps that have been approved by reviewers but unapproved by
        reviewers in special regions (e.g., China).

        """
        region = parse_region(region)
        column_prefix = '_geodata__region_%s' % region.slug
        return self.filter(**{
            'status': amo.STATUS_PUBLIC,
            'disabled_by_user': False,
            'escalationqueue__isnull': True,
            '%s_status' % column_prefix: amo.STATUS_PENDING,
        }).order_by('-%s_nominated' % column_prefix)

    def rated(self):
        """IARC."""
        if waffle.switch_is_active('iarc'):
            return self.exclude(content_ratings__isnull=True)
        return self

    def by_identifier(self, identifier):
        """
        Look up a single app by its `id` or `app_slug`.

        If the identifier is coercable into an integer, we first check for an
        ID match, falling back to a slug check (probably not necessary, as
        there is validation preventing numeric slugs). Otherwise, we only look
        for a slug match.
        """
        try:
            return self.get(id=identifier)
        except (ObjectDoesNotExist, ValueError):
            return self.get(app_slug=identifier)


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

            # Create Geodata object (a 1-to-1 relationship).
            if not hasattr(self, '_geodata'):
                Geodata.objects.create(addon=self)

    @staticmethod
    def transformer(apps):
        if not apps:
            return
        apps_dict = dict((a.id, a) for a in apps)

        # Only the parts relevant for Webapps are copied over from Addon. In
        # particular this avoids fetching categories and listed_authors, which
        # isn't useful in most parts of the Marketplace.

        # Set _latest_version, _current_version
        Addon.attach_related_versions(apps, apps_dict)

        # Attach previews. Don't use transforms, the only one present is for
        # translations and Previews don't have captions in the Marketplace, and
        # therefore don't have translations.
        Addon.attach_previews(apps, apps_dict, no_transforms=True)

        # Attach prices.
        Addon.attach_prices(apps, apps_dict)

        # FIXME: re-use attach_devices instead ?
        for adt in AddonDeviceType.objects.filter(addon__in=apps_dict):
            if not getattr(apps_dict[adt.addon_id], '_device_types', None):
                apps_dict[adt.addon_id]._device_types = []
            apps_dict[adt.addon_id]._device_types.append(
                DEVICE_TYPES[adt.device_type])

        # FIXME: attach geodata and content ratings. Maybe in a different
        # transformer that would then be called automatically for the API ?

    @staticmethod
    def version_and_file_transformer(apps):
        """Attach all the versions and files to the apps."""
        if not apps:
            return []

        ids = set(app.id for app in apps)
        versions = (Version.objects.no_cache().filter(addon__in=ids)
                    .select_related('addon'))
        vids = [v.id for v in versions]
        files = (File.objects.no_cache().filter(version__in=vids)
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

    @staticmethod
    def indexing_transformer(apps):
        """Attach everything we need to index apps."""
        transforms = (attach_categories, attach_devices, attach_prices,
                      attach_tags, attach_translations)
        for t in transforms:
            qs = apps.transform(t)
        return qs

    @property
    def geodata(self):
        if hasattr(self, '_geodata'):
            return self._geodata
        return Geodata.objects.get_or_create(addon=self)[0]

    def get_api_url(self, action=None, api=None, resource=None, pk=False):
        """Reverse a URL for the API."""
        if pk:
            key = self.pk
        else:
            key = self.app_slug
        return reverse('app-detail', kwargs={'pk': key})

    def get_url_path(self, more=False, add_prefix=True, src=None):
        # We won't have to do this when Marketplace absorbs all apps views,
        # but for now pretend you didn't see this.
        try:
            url_ = reverse('detail', args=[self.app_slug],
                           add_prefix=add_prefix)
        except NoReverseMatch:
            # Fall back to old details page until the views get ported.
            return super(Webapp, self).get_url_path(more=more,
                                                    add_prefix=add_prefix)
        else:
            if src is not None:
                return urlparams(url_, src=src)
            return url_

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

    def get_stats_url(self):
        return reverse('commonplace.stats.app_dashboard', args=[self.app_slug])

    def get_comm_thread_url(self):
        return reverse('commonplace.commbadge.app_dashboard',
                       args=[self.app_slug])

    @staticmethod
    def domain_from_url(url, allow_none=False):
        if not url:
            if allow_none:
                return
            raise ValueError('URL was empty')
        pieces = urlparse.urlparse(url)
        return '%s://%s' % (pieces.scheme, pieces.netloc.lower())

    @property
    def punycode_app_domain(self):
        return self.app_domain.encode('idna')

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
        if self.is_packaged:
            return self.app_domain

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
            if reviewer and self.latest_version:
                # Get latest version and return reviewer manifest URL.
                version = self.latest_version
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

        try:
            return file_.version.manifest
        except AppManifest.DoesNotExist:
            # TODO: Remove this when we're satisified the above is working.
            log.info('Falling back to loading manifest from file system. '
                     'Webapp:%s File:%s' % (self.id, file_.id))
            if file_.status == amo.STATUS_DISABLED:
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
        manifest = WebAppParser().get_json_data(upload)
        version = self.versions.latest()
        max_ = Version._meta.get_field_by_name('_developer_name')[0].max_length
        version.update(version=data['version'],
                       _developer_name=data['developer_name'][:max_])
        try:
            version.manifest_json.update(manifest=json.dumps(manifest))
        except AppManifest.DoesNotExist:
            AppManifest.objects.create(version=version,
                                       manifest=json.dumps(manifest))
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

    def has_incomplete_status(self):
        return self.is_incomplete()

    def details_errors(self):
        """
        See if initial app submission is complete (details).
        Returns list of reasons app may not be complete.
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
        return reasons

    def details_complete(self):
        """
        Checks if app detail submission is complete (first step of submit).
        """
        return not self.details_errors()

    def is_rated(self):
        return self.content_ratings.exists()

    def content_ratings_complete(self):
        """Checks for waffle."""
        return not waffle.switch_is_active('iarc') or self.is_rated()

    def has_payment_account(self):
        """App doesn't have a payment account set up yet."""
        return bool(self.payment_account)

    @amo.cached_property(writable=True)
    def payment_account(self):
        try:
            return self.app_payment_account
        except ObjectDoesNotExist:
            pass
        return None

    def payments_complete(self):
        """Also returns True if the app doesn't needs payments."""
        return not self.needs_payment() or self.has_payment_account()

    def completion_errors(self, ignore_ratings=False):
        """
        Compiles all submission steps into a single error report.

        ignore_ratings -- doesn't check for content_ratings for cases in which
                          content ratings were just created.
        """
        errors = {}

        if not self.details_complete():
            errors['details'] = self.details_errors()
        if not ignore_ratings and not self.content_ratings_complete():
            errors['content_ratings'] = _('You must set up content ratings.')
        if not self.payments_complete():
            errors['payments'] = _('You must set up a payment account.')

        return errors

    def completion_error_msgs(self):
        """Returns submission error messages as a flat list."""
        errors = self.completion_errors()
        # details is a list of msgs instead of a string like others.
        detail_errors = errors.pop('details', []) or []
        return detail_errors + errors.values()

    def is_fully_complete(self, ignore_ratings=False):
        """
        Wrapper to submission errors for readability and testability (mocking).
        """
        return not self.completion_errors(ignore_ratings)

    def next_step(self):
        """
        Gets the next step to fully complete app submission.
        """
        if self.has_incomplete_status() and not self.details_complete():
            # Some old public apps may have some missing detail fields.
            return {
                'name': _('Details'),
                'description': _('This app\'s submission process has not been '
                                 'fully completed.'),
                'url': self.get_dev_url(),
            }
        elif not self.content_ratings_complete():
            return {
                'name': _('Content Ratings'),
                'description': _('This app needs to get a content rating.'),
                'url': self.get_dev_url('ratings'),
            }
        elif not self.payments_complete():
            return {
                'name': _('Payments'),
                'description': _('This app needs a payment account set up.'),
                'url': self.get_dev_url('payments'),
            }

    @amo.cached_property(writable=True)
    def is_offline(self):
        """
        Returns a boolean of whether this is an app that degrades
        gracefully offline (i.e., is a packaged app or has an
        `appcache_path` defined in its manifest).

        """
        if self.is_packaged:
            return True
        manifest = self.get_manifest_json()
        return bool(manifest and 'appcache_path' in manifest)

    def mark_done(self):
        """When the submission process is done, update status accordingly."""
        self.update(status=amo.WEBAPPS_UNREVIEWED_STATUS)

    def update_status(self, **kwargs):
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

        # If the app is incomplete, don't update status.
        if not self.is_fully_complete():
            return

        # If there are no public versions and at least one pending, set status
        # to pending.
        public_statuses = amo.WEBAPPS_APPROVED_STATUSES
        has_public = (
            self.versions.filter(files__status__in=public_statuses).exists()
        )
        has_pending = (
            self.versions.filter(files__status=amo.STATUS_PENDING).exists())
        # Check for self.is_pending() first to prevent possible recursion.
        if not has_public and has_pending and not self.is_pending():
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
    def can_be_purchased(self):
        return self.is_premium() and self.status in amo.REVIEWED_STATUSES

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

        user_region = getattr(request, 'REGION', mkt.regions.RESTOFWORLD)

        # See if it's a game without a content rating.
        for region in mkt.regions.ALL_REGIONS_WITH_CONTENT_RATINGS():
            if (user_region == region and self.listed_in(category='games') and
                not self.content_ratings_in(region, 'games')):
                unrated_game = True
            else:
                unrated_game = False

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
        elif self.is_public() and not unrated_game:
            # Everyone else can see it only if it's public -
            # and if it's a game, it must have a content rating.
            visible = True

        return visible

    def has_premium(self):
        """If the app is premium status and has a premium object."""
        return bool(self.is_premium() and self.premium)

    def get_price(self, carrier=None, region=None, provider=None):
        """
        A shortcut to get the price as decimal. Returns None if their is no
        price for the app.

        :param optional carrier: an int for the carrier.
        :param optional region: an int for the region. Defaults to restofworld.
        :param optional provider: an int for the provider. Defaults to bango.
        """
        if self.has_premium() and self.premium.price:
            return self.premium.price.get_price(carrier=carrier, region=region,
                                                provider=provider)

    def get_price_locale(self, carrier=None, region=None, provider=None):
        """
        A shortcut to get the localised price with currency. Returns None if
        their is no price for the app.

        :param optional carrier: an int for the carrier.
        :param optional region: an int for the region. Defaults to restofworld.
        :param optional provider: an int for the provider. Defaults to bango.
        """
        if self.has_premium() and self.premium.price:
            return self.premium.price.get_price_locale(
                carrier=carrier, region=region, provider=provider)

    def get_tier(self):
        """
        Returns the price tier object.
        """
        if self.has_premium():
            return self.premium.price

    def get_tier_name(self):
        """
        Returns the price tier for showing prices in the reviewer
        tools and developer hub.
        """
        tier = self.get_tier()
        if tier:
            return tier.tier_locale()

    @amo.cached_property
    def promo(self):
        return self.get_promo()

    def get_promo(self):
        try:
            return self.previews.filter(position=-1)[0]
        except IndexError:
            pass

    def get_region_ids(self, restofworld=False, excluded=None):
        """
        Return IDs of regions in which this app is listed.

        If `excluded` is provided we'll use that instead of doing our own
        excluded lookup.
        """
        if restofworld:
            all_ids = mkt.regions.ALL_REGION_IDS
        else:
            all_ids = mkt.regions.REGION_IDS
        if excluded is None:
            excluded = list(self.addonexcludedregion
                                .values_list('region', flat=True))

        return sorted(set(all_ids) - set(excluded or []))

    def get_excluded_region_ids(self):
        """
        Return IDs of regions for which this app is excluded.

        This will be all the addon excluded regions. If the app is premium,
        this will also exclude any region that does not have the price tier
        set.

        Note: free and in-app are not included in this.
        """
        excluded = set(self.addonexcludedregion
                           .values_list('region', flat=True))

        if self.is_premium():
            all_regions = set(mkt.regions.ALL_REGION_IDS)
            # Find every region that does not have payments supported
            # and add that into the exclusions.
            return excluded.union(
                all_regions.difference(self.get_price_region_ids()))

        return sorted(list(excluded))

    def get_price_region_ids(self):
        tier = self.get_tier()
        if tier:
            return sorted(p['region'] for p in tier.prices() if p['paid'])
        return []

    def get_regions(self, regions=None):
        """
        Return a list of regions objects the app is available in, e.g.:
            [<class 'mkt.constants.regions.BR'>,
             <class 'mkt.constants.regions.CA'>,
             <class 'mkt.constants.regions.UK'>,
             <class 'mkt.constants.regions.US'>,
             <class 'mkt.constants.regions.RESTOFWORLD'>]

        if `regions` is provided we'll use that instead of calling
        self.get_region_ids()
        """
        regions_ids = regions or self.get_region_ids(restofworld=True)
        _regions = map(mkt.regions.REGIONS_CHOICES_ID_DICT.get, regions_ids)
        return sorted(_regions, key=lambda x: x.slug)

    def listed_in(self, region=None, category=None):
        listed = []
        if region:
            listed.append(region.id in self.get_region_ids(restofworld=True))
        if category:
            if isinstance(category, basestring):
                filters = {'slug': category}
            else:
                filters = {'id': category.id}
            listed.append(self.category_set.filter(**filters).exists())
        return all(listed or [False])

    def content_ratings_in(self, region, category=None):
        """
        Get all content ratings for this app in REGION for CATEGORY.
        (e.g. give me the content ratings for a game listed in a Brazil.)
        """

        # If we want to find games in Brazil with content ratings, then
        # make sure it's actually listed in Brazil and it's a game.
        if category and not self.listed_in(region, category):
            return []

        rb = []
        if not region.ratingsbody:
            # If a region doesn't specify a ratings body, default to GENERIC.
            rb = mkt.ratingsbodies.GENERIC.id
        else:
            rb = region.ratingsbody.id

        return list(self.content_ratings.filter(ratings_body=rb)
                        .order_by('rating'))

    @classmethod
    def now(cls):
        return datetime.date.today()

    @classmethod
    def from_search(cls, request, cat=None, region=None, gaia=False,
                    mobile=False, tablet=False, filter_overrides=None):

        filters = {
            'type': amo.ADDON_WEBAPP,
            'status': amo.STATUS_PUBLIC,
            'is_disabled': False,
        }

        # Special handling if status is 'any' to remove status filter.
        if filter_overrides and 'status' in filter_overrides:
            if filter_overrides['status'] is 'any':
                del filters['status']
                del filter_overrides['status']

        if filter_overrides:
            filters.update(filter_overrides)

        if cat:
            filters.update(category=cat.slug)

        srch = S(WebappIndexer).filter(**filters)

        if (region and
            not waffle.flag_is_active(request, 'override-region-exclusion')):
            srch = srch.filter(~F(region_exclusions=region.id))

        if mobile or gaia:
            srch = srch.filter(uses_flash=False)

        return srch

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
            manifest = self.get_manifest_json(file_obj)
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
        mf = WebAppParser().get_json_data(f.file_path)
        AppManifest.objects.create(version=v, manifest=json.dumps(mf))
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

        file_ = self.current_version.all_files[0]
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

    def update_supported_locales(self, latest=False, manifest=None):
        """
        Loads the manifest (for either hosted or packaged) and updates
        Version.supported_locales for the current version or latest version if
        latest=True.
        """
        version = self.versions.latest() if latest else self.current_version

        if not manifest:
            file_ = version.all_files[0]
            manifest = self.get_manifest_json(file_)

        updated = False

        supported_locales = ','.join(get_supported_locales(manifest))
        if version.supported_locales != supported_locales:
            updated = True
            version.update(supported_locales=supported_locales, _signal=False)

        return updated

    @property
    def app_type_id(self):
        """
        Returns int of `1` (hosted), `2` (packaged), or `3` (privileged).
        Used by ES.
        """
        if self.latest_version and self.latest_version.is_privileged:
            return amo.ADDON_WEBAPP_PRIVILEGED
        elif self.is_packaged:
            return amo.ADDON_WEBAPP_PACKAGED
        return amo.ADDON_WEBAPP_HOSTED

    @property
    def app_type(self):
        """
        Returns string of 'hosted', 'packaged', or 'privileged'.
        Used in the API.
        """
        return amo.ADDON_WEBAPP_TYPES[self.app_type_id]

    @property
    def supported_locales(self):
        """
        Returns a tuple of the form:

            (localized default_locale, list of localized supported locales)

        for the current public version.

        """
        languages = []
        version = self.current_version

        if version:
            for locale in version.supported_locales.split(','):
                if locale:
                    language = settings.LANGUAGES.get(locale.lower())
                    if language:
                        languages.append(language)

        return (
            settings.LANGUAGES.get(self.default_locale.lower()),
            sorted(languages)
        )

    @property
    def developer_name(self):
        """This is the developer name extracted from the manifest."""
        if self.current_version:
            return self.current_version.developer_name

    def get_trending(self, region=None):
        """
        Returns trending value.

        If no region, uses global value.
        If region and region is not mature, uses global value.
        Otherwise uses regional trending value.

        """
        if region and not region.adolescent:
            by_region = region.id
        else:
            by_region = 0

        try:
            return self.trending.get(region=by_region).value
        except ObjectDoesNotExist:
            return 0

    def iarc_token(self):
        """
        Simple hash to verify token in pingback API.
        """
        return hashlib.sha512(settings.SECRET_KEY + str(self.id)).hexdigest()

    def get_content_ratings_by_body(self, es=False):
        """
        Gets content ratings on this app keyed by bodies.

        es -- denotes whether to return ES-friendly results (just the IDs of
              rating classes) to fetch and translate later.
        region -- region slug in case we know the region when serializing and
                  want to limit the response size.
        """
        content_ratings = {}
        for cr in self.content_ratings.all():
            body = cr.get_body()
            rating_serialized = {
                'body': body.id,
                'rating': cr.get_rating().id
            }
            if not es:
                rating_serialized = dehydrate_content_rating(rating_serialized)
            content_ratings[body.label] = rating_serialized

        return content_ratings

    def get_descriptors(self, es=False):
        """
        Return lists of serialized content descriptors by body.
        (e.g. {
            'esrb': [{'label': 'esrb-blood', 'name': u'Blood}],
            'pegi': [{'label': 'classind-lang', 'name': u'Language'}]}
        )

        es -- denotes whether to return ES-friendly results (just the keys of
              the descriptors) to fetch and dehydrate later.
              (e.g. ['ESRB_BLOOD', 'CLASSIND_LANG').

        """
        try:
            app_descriptors = self.rating_descriptors
        except RatingDescriptors.DoesNotExist:
            if es:
                return []  # Serialized for ES.
            return {}  # Dehydrated.

        descriptors = []
        for key in mkt.ratingdescriptors.RATING_DESCS.keys():
            field = 'has_%s' % key.lower()  # Build the field name.
            if getattr(app_descriptors, field):
                descriptors.append(key)

        if not es:
            # Convert the descriptor names into descriptor objects.
            descriptors = dehydrate_descriptors(descriptors)
        return descriptors

    def get_interactives(self, es=False):
        """
        Return list of serialized interactive elements.
        (e.g. [{'label': 'social-networking', 'name': u'Social Networking'},
               {'label': 'milk', 'name': u'Milk'}])

        es -- denotes whether to return ES-friendly results (just the keys of
              the interactive elements) to fetch and dehydrate later.
              (e.g. ['SOCIAL_NETWORKING', 'MILK'])

        """
        try:
            app_interactives = self.rating_interactives
        except RatingInteractives.DoesNotExist:
            return []

        interactives = []
        for key in mkt.ratinginteractives.RATING_INTERACTIVES.keys():
            field = 'has_%s' % key.lower()
            if getattr(app_interactives, field):
                interactives.append(key)

        if not es and interactives:
            interactives = dehydrate_interactives(interactives)
        return interactives

    def set_iarc_info(self, submission_id, security_code):
        """
        Sets the iarc_info for this app.
        """
        data = {'submission_id': submission_id,
                'security_code': security_code}
        info, created = IARCInfo.objects.safer_get_or_create(
            addon=self, defaults=data)
        if not created:
            info.update(**data)

    @write
    def set_content_ratings(self, data):
        """
        Central method for setting content ratings.

        This overwrites or creates ratings, it doesn't delete and expects data
        of the form::

            {<ratingsbodies class>: <rating class>, ...}

        """
        from . import tasks

        if not data:
            return

        log.info('IARC setting content ratings for app:%s:%s' %
                 (self.id, self.app_slug))

        for ratings_body, rating in data.items():
            cr, created = self.content_ratings.safer_get_or_create(
                ratings_body=ratings_body.id, defaults={'rating': rating.id})
            if not created:
                cr.update(rating=rating.id, modified=datetime.datetime.now())

        log.info('IARC content ratings set for app:%s:%s' %
                 (self.id, self.app_slug))

        self.set_iarc_storefront_data()  # Ratings updated, sync with IARC.

        geodata, c = Geodata.objects.get_or_create(addon=self)
        save = False

        # If app gets USK Rating Refused, exclude it from Germany.
        has_usk_refused = self.content_ratings.filter(
            ratings_body=mkt.ratingsbodies.USK.id,
            rating=mkt.ratingsbodies.USK_REJECTED.id).exists()
        save = geodata.region_de_usk_exclude != has_usk_refused
        geodata.region_de_usk_exclude = has_usk_refused

        # Un-exclude games in Brazil/Germany once they get a content rating.
        save = (save or geodata.region_br_iarc_exclude or
                geodata.region_de_iarc_exclude)
        geodata.region_br_iarc_exclude = False
        geodata.region_de_iarc_exclude = False

        if save:
            geodata.save()
            log.info('Un-excluding IARC-excluded app:%s from br/de')

        tasks.index_webapps.delay([self.id])

    @write
    def set_descriptors(self, data):
        """
        Sets IARC rating descriptors on this app.

        This overwrites or creates elements, it doesn't delete and expects data
        of the form:

            [<has_descriptor_1>, <has_descriptor_6>]

        """
        log.info('IARC setting descriptors for app:%s:%s' %
                 (self.id, self.app_slug))

        create_kwargs = {}
        for desc in mkt.ratingdescriptors.RATING_DESCS.keys():
            has_desc_attr = 'has_%s' % desc.lower()
            create_kwargs[has_desc_attr] = has_desc_attr in data

        rd, created = RatingDescriptors.objects.get_or_create(
            addon=self, defaults=create_kwargs)
        if not created:
            rd.update(**create_kwargs)

        log.info('IARC descriptors set for app:%s:%s' %
                 (self.id, self.app_slug))

    @write
    def set_interactives(self, data):
        """
        Sets IARC interactive elements on this app.

        This overwrites or creates elements, it doesn't delete and expects data
        of the form:

            [<has_interactive_1>, <has_interactive name 2>]

        """
        create_kwargs = {}
        for interactive in mkt.ratinginteractives.RATING_INTERACTIVES.keys():
            interactive = 'has_%s' % interactive.lower()
            create_kwargs[interactive] = interactive in map(
                lambda x: x.lower(), data)

        ri, created = RatingInteractives.objects.get_or_create(
            addon=self, defaults=create_kwargs)
        if not created:
            ri.update(**create_kwargs)

        log.info('IARC interactive elements set for app:%s:%s' %
                 (self.id, self.app_slug))

    def set_iarc_storefront_data(self, disable=False):
        """Send app data to IARC for them to verify."""
        if not waffle.switch_is_active('iarc'):
            return

        try:
            iarc_info = self.iarc_info
        except IARCInfo.DoesNotExist:
            # App wasn't rated by IARC, return.
            return

        release_date = datetime.date.today()

        if self.status in amo.WEBAPPS_APPROVED_STATUSES:
            version = self.current_version
            reviewed = self.current_version.reviewed
            if reviewed:
                release_date = reviewed
        elif self.status in amo.WEBAPPS_EXCLUDED_STATUSES:
            # Using `_latest_version` since the property returns None when
            # deleted.
            version = self._latest_version
            # Send an empty string to signify the app was removed.
            release_date = ''
        else:
            # If not approved or one of the disabled statuses, we shouldn't be
            # calling SET_STOREFRONT_DATA. Ignore this call.
            return

        log.debug('Calling SET_STOREFRONT_DATA for app:%s' % self.id)

        xmls = []
        for cr in self.content_ratings.all():
            xmls.append(render_xml('set_storefront_data.xml', {
                'submission_id': iarc_info.submission_id,
                'security_code': iarc_info.security_code,
                'rating_system': cr.get_body().iarc_name,
                'release_date': '' if disable else release_date,
                'title': get_iarc_app_title(self),
                'company': version.developer_name,
                'rating': cr.get_rating().iarc_name,
                'descriptors': self.rating_descriptors.iarc_deserialize(
                    body=cr.get_body()),
                'interactive_elements':
                    self.rating_interactives.iarc_deserialize(),
            }))

        for xml in xmls:
            r = get_iarc_client('services').Set_Storefront_Data(XMLString=xml)
            log.debug('IARC result app:%s, rating_body:%s: %s' % (
                self.id, cr.get_body().iarc_name, r))

    def last_rated_time(self):
        """Most recent content rating modified time or None if not rated."""
        if self.is_rated():
            return self.content_ratings.order_by('-modified')[0].modified


class Trending(amo.models.ModelBase):
    addon = models.ForeignKey(Addon, related_name='trending')
    value = models.FloatField(default=0.0)
    # When region=0, it's trending using install counts across all regions.
    region = models.PositiveIntegerField(null=False, default=0, db_index=True)

    class Meta:
        db_table = 'addons_trending'
        unique_together = ('addon', 'region')


class WebappIndexer(MappingType, Indexable):
    """
    Mapping type for Webapp models.

    By default we will return these objects rather than hit the database so
    include here all the things we need to avoid hitting the database.
    """

    @classmethod
    def get_mapping_type_name(cls):
        """
        Returns mapping type name which is used as the key in ES_INDEXES to
        determine which index to use.

        We override this because Webapp is a proxy model to Addon.
        """
        return 'webapp'

    @classmethod
    def get_index(cls):
        return settings.ES_INDEXES[cls.get_mapping_type_name()]

    @classmethod
    def get_model(cls):
        return Webapp

    @classmethod
    def get_settings(cls, settings_override=None):
        """
        Returns settings to be passed to ES create_index.

        If `settings_override` is provided, this will use `settings_override`
        to override the defaults defined here.

        """
        default_settings = {
            'number_of_replicas': settings.ES_DEFAULT_NUM_REPLICAS,
            'number_of_shards': settings.ES_DEFAULT_NUM_SHARDS,
            'refresh_interval': '5s',
            'store.compress.tv': True,
            'store.compress.stored': True,
            'analysis': cls.get_analysis(),
        }
        if settings_override:
            default_settings.update(settings_override)

        return default_settings

    @classmethod
    def get_analysis(cls):
        """
        Returns the analysis dict to be used in settings for create_index.

        For languages that ES supports we define either the minimal or light
        stemming, which isn't as aggresive as the snowball stemmer. We also
        define the stopwords for that language.

        For all languages we've customized we're using the ICU plugin.

        """
        filters = {}
        analyzers = {}

        # Customize the word_delimiter filter to set various options.
        filters['custom_word_delimiter'] = {
            'type': 'word_delimiter',
            'preserve_original': True,
        }

        # The default is used for fields that need ICU but are composed of
        # many languages.
        analyzers['default_icu'] = {
            'type': 'custom',
            'tokenizer': 'icu_tokenizer',
            'filter': ['custom_word_delimiter', 'icu_folding',
                       'icu_normalizer'],
        }

        for lang, stemmer in amo.STEMMER_MAP.items():
            filters['%s_stem_filter' % lang] = {
                'type': 'stemmer',
                'name': stemmer,
            }
            filters['%s_stop_filter' % lang] = {
                'type': 'stop',
                'stopwords': ['_%s_' % lang],
            }

            analyzers['%s_analyzer' % lang] = {
                'type': 'custom',
                'tokenizer': 'icu_tokenizer',
                'filter': [
                    'custom_word_delimiter', 'icu_folding', 'icu_normalizer',
                    '%s_stop_filter' % lang, '%s_stem_filter' % lang
                ],
            }

        return {
            'analyzer': analyzers,
            'filter': filters,
        }

    @classmethod
    def setup_mapping(cls):
        """Creates the ES index/mapping."""
        cls.get_es().create_index(cls.get_index(),
                                  {'mappings': cls.get_mapping(),
                                   'settings': cls.get_settings()})

    @classmethod
    def get_mapping(cls):

        doc_type = cls.get_mapping_type_name()

        def _locale_field_mapping(field, analyzer):
            get_analyzer = lambda a: (
                '%s_analyzer' % a if a in amo.STEMMER_MAP else a)
            return {'%s_%s' % (field, analyzer): {
                'type': 'string', 'analyzer': get_analyzer(analyzer)}}

        mapping = {
            doc_type: {
                # Disable _all field to reduce index size.
                '_all': {'enabled': False},
                # Add a boost field to enhance relevancy of a document.
                '_boost': {'name': '_boost', 'null_value': 1.0},
                'properties': {
                    'id': {'type': 'long'},
                    'app_slug': {'type': 'string'},
                    'app_type': {'type': 'byte'},
                    'author': {'type': 'string'},
                    'average_daily_users': {'type': 'long'},
                    'banner_regions': {
                        'type': 'string',
                        'index': 'not_analyzed'
                    },
                    'bayesian_rating': {'type': 'float'},
                    'category': {
                        'type': 'string',
                        'index': 'not_analyzed'
                    },
                    'collection': {
                        'type': 'nested',
                        'include_in_parent': True,
                        'properties': {
                            'id': {'type': 'long'},
                            'order': {'type': 'short'}
                        }
                    },
                    'content_descriptors': {
                        'type': 'string',
                        'index': 'not_analyzed'
                    },
                    'content_ratings': {
                        'type': 'object',
                        'dynamic': 'true',
                    },
                    'created': {'format': 'dateOptionalTime', 'type': 'date'},
                    'current_version': {'type': 'string',
                                        'index': 'not_analyzed'},
                    'default_locale': {'type': 'string',
                                       'index': 'not_analyzed'},
                    'description': {'type': 'string',
                                    'analyzer': 'default_icu'},
                    'device': {'type': 'byte'},
                    'features': {
                        'type': 'object',
                        'properties': dict(
                            ('has_%s' % f.lower(), {'type': 'boolean'})
                            for f in APP_FEATURES)
                    },
                    'has_public_stats': {'type': 'boolean'},
                    'icons': {
                        'type': 'object',
                        'properties': {
                            'size': {'type': 'short'},
                        }
                    },
                    'interactive_elements': {
                        'type': 'string',
                        'index': 'not_analyzed'
                    },
                    'is_disabled': {'type': 'boolean'},
                    'is_escalated': {'type': 'boolean'},
                    'is_offline': {'type': 'boolean'},
                    'last_updated': {'format': 'dateOptionalTime',
                                     'type': 'date'},
                    'latest_version': {
                        'type': 'object',
                        'properties': {
                            'status': {'type': 'byte'},
                            'is_privileged': {'type': 'boolean'},
                            'has_editor_comment': {'type': 'boolean'},
                            'has_info_request': {'type': 'boolean'},
                        },
                    },
                    'manifest_url': {'type': 'string',
                                     'index': 'not_analyzed'},
                    'modified': {'format': 'dateOptionalTime',
                                 'type': 'date',
                                 'index': 'not_analyzed'},
                    # Name for searching.
                    'name': {'type': 'string', 'analyzer': 'default_icu'},
                    # Name for sorting.
                    'name_sort': {'type': 'string', 'index': 'not_analyzed'},
                    'owners': {'type': 'long'},
                    'popularity': {'type': 'long'},
                    'premium_type': {'type': 'byte'},
                    'previews': {
                        'type': 'object',
                        'dynamic': 'true',
                    },
                    'price_tier': {'type': 'string',
                                   'index': 'not_analyzed'},
                    'ratings': {
                        'type': 'object',
                        'properties': {
                            'average': {'type': 'float'},
                            'count': {'type': 'short'},
                        }
                    },
                    'region_exclusions': {'type': 'short'},
                    'reviewed': {'format': 'dateOptionalTime', 'type': 'date'},
                    'status': {'type': 'byte'},
                    'supported_locales': {'type': 'string',
                                          'index': 'not_analyzed'},
                    'tags': {'type': 'string', 'analyzer': 'simple'},
                    'type': {'type': 'byte'},
                    'upsell': {
                        'type': 'object',
                        'properties': {
                            'id': {'type': 'long'},
                            'app_slug': {'type': 'string',
                                         'index': 'not_analyzed'},
                            'icon_url': {'type': 'string',
                                         'index': 'not_analyzed'},
                            'name': {'type': 'string',
                                     'index': 'not_analyzed'},
                            'region_exclusions': {'type': 'short'},
                        }
                    },
                    'uses_flash': {'type': 'boolean'},
                    'versions': {
                        'type': 'object',
                        'properties': {
                            'version': {'type': 'string',
                                        'index': 'not_analyzed'},
                            'resource_uri': {'type': 'string',
                                             'index': 'not_analyzed'},
                        }
                    },
                    'weekly_downloads': {'type': 'long'},
                }
            }
        }

        # Add popularity by region.
        for region in mkt.regions.ALL_REGION_IDS:
            mapping[doc_type]['properties'].update(
                {'popularity_%s' % region: {'type': 'long'}})

        # Add fields that we expect to return all translations.
        for field in ('banner_message', 'description', 'homepage', 'name',
                      'release_notes', 'support_email', 'support_url'):
            mapping[doc_type]['properties'].update({
                '%s_translations' % field: {
                    'type': 'object',
                    'properties': {
                        'lang': {'type': 'string',
                                 'index': 'not_analyzed'},
                        'string': {'type': 'string',
                                   'index': 'not_analyzed'},
                    }
                }
            })

        # Add room for language-specific indexes.
        for analyzer in amo.SEARCH_ANALYZER_MAP:
            if (not settings.ES_USE_PLUGINS and
                analyzer in amo.SEARCH_ANALYZER_PLUGINS):
                log.info('While creating mapping, skipping the %s analyzer'
                         % analyzer)
                continue

            mapping[doc_type]['properties'].update(
                _locale_field_mapping('name', analyzer))
            mapping[doc_type]['properties'].update(
                _locale_field_mapping('description', analyzer))

        # TODO: reviewer flags (bug 848446)

        return mapping

    @classmethod
    def extract_document(cls, pk, obj=None):
        """Extracts the ElasticSearch index document for this instance."""
        if obj is None:
            obj = cls.get_model().objects.no_cache().get(pk=pk)

        latest_version = obj.latest_version
        version = obj.current_version
        geodata = obj.geodata
        features = (version.features.to_dict()
                    if version else AppFeatures().to_dict())
        is_escalated = obj.escalationqueue_set.exists()

        try:
            status = latest_version.statuses[0][1] if latest_version else None
        except IndexError:
            status = None

        installed_ids = list(Installed.objects.filter(addon=obj)
                             .values_list('id', flat=True))

        attrs = ('app_slug', 'average_daily_users', 'bayesian_rating',
                 'created', 'id', 'is_disabled', 'last_updated', 'modified',
                 'premium_type', 'status', 'type', 'uses_flash',
                 'weekly_downloads')
        d = dict(zip(attrs, attrgetter(*attrs)(obj)))

        d['app_type'] = obj.app_type_id
        d['author'] = obj.developer_name
        d['banner_regions'] = geodata.banner_regions_slugs()
        d['category'] = list(obj.categories.values_list('slug', flat=True))
        if obj.is_public:
            d['collection'] = [{'id': cms.collection_id, 'order': cms.order}
                               for cms in obj.collectionmembership_set.all()]
        else:
            d['collection'] = []
        d['content_ratings'] = (obj.get_content_ratings_by_body(es=True) or
                                None)
        d['content_descriptors'] = obj.get_descriptors(es=True)
        d['current_version'] = version.version if version else None
        d['default_locale'] = obj.default_locale
        d['description'] = list(
            set(string for _, string in obj.translations[obj.description_id]))
        d['device'] = getattr(obj, 'device_ids', [])
        d['features'] = features
        d['has_public_stats'] = obj.public_stats
        d['icons'] = [{'size': icon_size} for icon_size in (16, 48, 64, 128)]
        d['interactive_elements'] = obj.get_interactives(es=True)
        d['is_escalated'] = is_escalated
        d['is_offline'] = getattr(obj, 'is_offline', False)
        if latest_version:
            d['latest_version'] = {
                'status': status,
                'is_privileged': latest_version.is_privileged,
                'has_editor_comment': latest_version.has_editor_comment,
                'has_info_request': latest_version.has_info_request,
            }
        else:
            d['latest_version'] = {
                'status': None,
                'is_privileged': None,
                'has_editor_comment': None,
                'has_info_request': None,
            }
        d['manifest_url'] = obj.get_manifest_url()
        d['name'] = list(
            set(string for _, string in obj.translations[obj.name_id]))
        d['name_sort'] = unicode(obj.name).lower()
        d['owners'] = [au.user.id for au in
                       obj.addonuser_set.filter(role=amo.AUTHOR_ROLE_OWNER)]
        d['popularity'] = d['_boost'] = len(installed_ids)
        d['previews'] = [{'filetype': p.filetype, 'modified': p.modified,
                          'id': p.id} for p in obj.previews.all()]
        try:
            p = obj.addonpremium.price
            d['price_tier'] = p.name
        except AddonPremium.DoesNotExist:
            d['price_tier'] = None

        d['ratings'] = {
            'average': obj.average_rating,
            'count': obj.total_reviews,
        }
        d['region_exclusions'] = obj.get_excluded_region_ids()
        d['reviewed'] = obj.versions.filter(
            deleted=False).aggregate(Min('reviewed')).get('reviewed__min')
        if version:
            d['supported_locales'] = filter(
                None, version.supported_locales.split(','))
        else:
            d['supported_locales'] = []

        d['tags'] = getattr(obj, 'tag_list', [])
        if obj.upsell and obj.upsell.premium.is_public():
            upsell_obj = obj.upsell.premium
            d['upsell'] = {
                'id': upsell_obj.id,
                'app_slug': upsell_obj.app_slug,
                'icon_url': upsell_obj.get_icon_url(128),
                # TODO: Store all localizations of upsell.name.
                'name': unicode(upsell_obj.name),
                'region_exclusions': upsell_obj.get_excluded_region_ids()
            }

        d['versions'] = [dict(version=v.version,
                              resource_uri=reverse_version(v))
                         for v in obj.versions.all()]

        # Handle our localized fields.
        for field in ('description', 'homepage', 'name', 'support_email',
                      'support_url'):
            d['%s_translations' % field] = [
                {'lang': to_language(lang), 'string': string}
                for lang, string
                in obj.translations[getattr(obj, '%s_id' % field)]
                if string]
        if version:
            amo.utils.attach_trans_dict(Version, [version])
            d['release_notes_translations'] = [
                {'lang': to_language(lang), 'string': string}
                for lang, string
                in version.translations[version.releasenotes_id]]
        else:
            d['release_notes_translations'] = None
        amo.utils.attach_trans_dict(Geodata, [geodata])
        d['banner_message_translations'] = [
            {'lang': to_language(lang), 'string': string}
            for lang, string
            in geodata.translations[geodata.banner_message_id]]

        # Calculate regional popularity for "mature regions"
        # (installs + reviews/installs from that region).
        installs = dict(ClientData.objects.filter(installed__in=installed_ids)
                        .annotate(region_counts=models.Count('region'))
                        .values_list('region', 'region_counts').distinct())
        for region in mkt.regions.ALL_REGION_IDS:
            cnt = installs.get(region, 0)
            if cnt:
                # Magic number (like all other scores up in this piece).
                d['popularity_%s' % region] = d['popularity'] + cnt * 10
            else:
                d['popularity_%s' % region] = len(installed_ids)
            d['_boost'] += cnt * 10

        # Bump the boost if the add-on is public.
        if obj.status == amo.STATUS_PUBLIC:
            d['_boost'] = max(d['_boost'], 1) * 4

        # Indices for each language. languages is a list of locales we want to
        # index with analyzer if the string's locale matches.
        for analyzer, languages in amo.SEARCH_ANALYZER_MAP.iteritems():
            if (not settings.ES_USE_PLUGINS and
                analyzer in amo.SEARCH_ANALYZER_PLUGINS):
                continue

            d['name_' + analyzer] = list(
                set(string for locale, string in obj.translations[obj.name_id]
                    if locale.lower() in languages))
            d['description_' + analyzer] = list(
                set(string for locale, string
                    in obj.translations[obj.description_id]
                    if locale.lower() in languages))

        return d

    @classmethod
    def get_indexable(cls):
        """Returns the queryset of ids of all things to be indexed."""
        return (Webapp.with_deleted.all()
                .order_by('-id').values_list('id', flat=True))


# Set translated_fields manually to avoid querying translations for addon
# fields we don't use.
Webapp._meta.translated_fields = [
    Webapp._meta.get_field('homepage'),
    Webapp._meta.get_field('privacy_policy'),
    Webapp._meta.get_field('name'),
    Webapp._meta.get_field('description'),
    Webapp._meta.get_field('support_email'),
    Webapp._meta.get_field('support_url'),
]


@receiver(dbsignals.post_save, sender=Webapp,
          dispatch_uid='webapp.search.index')
def update_search_index(sender, instance, **kw):
    from . import tasks
    if not kw.get('raw'):
        if instance.upsold and instance.upsold.free_id:
            tasks.index_webapps.delay([instance.upsold.free_id])
        tasks.index_webapps.delay([instance.id])


@receiver(dbsignals.post_save, sender=AddonUpsell,
          dispatch_uid='addonupsell.search.index')
def update_search_index_upsell(sender, instance, **kw):
    # When saving an AddonUpsell instance, reindex both apps to update their
    # upsell/upsold properties in ES.
    from . import tasks
    if instance.free:
        tasks.index_webapps.delay([instance.free.id])
    if instance.premium:
        tasks.index_webapps.delay([instance.premium.id])


models.signals.pre_save.connect(save_signal, sender=Webapp,
                                dispatch_uid='webapp_translations')


@receiver(version_changed, dispatch_uid='update_cached_manifests')
def update_cached_manifests(sender, **kw):
    if not kw.get('raw') and sender.is_packaged:
        from mkt.webapps.tasks import update_cached_manifests
        update_cached_manifests.delay(sender.id)


@Webapp.on_change
def watch_status(old_attr={}, new_attr={}, instance=None, sender=None, **kw):
    """Set nomination date when app is pending review."""
    new_status = new_attr.get('status')
    if not new_status:
        return
    addon = instance
    if new_status == amo.STATUS_PENDING and old_attr['status'] != new_status:
        # We always set nomination date when app switches to PENDING, even if
        # previously rejected.
        try:
            latest = addon.versions.latest()
            log.debug('[Webapp:%s] Setting nomination date to now.' % addon.id)
            latest.update(nomination=datetime.datetime.now())
        except Version.DoesNotExist:
            log.debug('[Webapp:%s] Missing version, no nomination set.'
                      % addon.id)
            pass


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


@memoize(prefix='get_excluded_in')
def get_excluded_in(region_id):
    """
    Return IDs of Webapp objects excluded from a particular region or excluded
    due to Geodata flags.
    """
    aers = list(AddonExcludedRegion.objects.filter(region=region_id)
                .values_list('addon', flat=True))

    # For pre-IARC unrated games in Brazil/Germany.
    geodata_qs = Q()
    region = parse_region(region_id)
    if region in (mkt.regions.BR, mkt.regions.DE):
        geodata_qs |= Q(**{'region_%s_iarc_exclude' % region.slug: True})
    # For USK_RATING_REFUSED apps in Germany.
    if region == mkt.regions.DE:
        geodata_qs |= Q(**{'region_de_usk_exclude': True})

    geodata_exclusions = []
    if geodata_qs:
        geodata_exclusions = list(Geodata.objects.filter(geodata_qs)
                                  .values_list('addon', flat=True))
    return set(aers + geodata_exclusions)


@receiver(models.signals.post_save, sender=AddonExcludedRegion,
          dispatch_uid='clean_memoized_exclusions')
def clean_memoized_exclusions(sender, **kw):
    if not kw.get('raw'):
        for k in mkt.regions.ALL_REGION_IDS:
            cache.delete_many([memoize_key('get_excluded_in', k)
                               for k in mkt.regions.ALL_REGION_IDS])


class IARCInfo(amo.models.ModelBase):
    """
    Stored data for IARC.
    """
    addon = models.OneToOneField(Addon, related_name='iarc_info')
    submission_id = models.PositiveIntegerField(null=False)
    security_code = models.CharField(max_length=10)

    class Meta:
        db_table = 'webapps_iarc_info'
        unique_together = ('addon', 'submission_id')

    def __unicode__(self):
        return u'app:%s' % self.addon.app_slug


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

    class Meta:
        db_table = 'webapps_contentrating'
        unique_together = ('addon', 'ratings_body')

    def __unicode__(self):
        return u'%s: %s' % (self.addon, self.get_label())

    def get_regions(self):
        """Gives us a list of Region classes that use this rating body."""
        # All regions w/o specified ratings bodies fallback to Generic.
        generic_regions = []
        if (waffle.switch_is_active('iarc') and
            self.get_body_class() == mkt.ratingsbodies.GENERIC):
            generic_regions = mkt.regions.ALL_REGIONS_WITHOUT_CONTENT_RATINGS()

        return ([x for x in mkt.regions.ALL_REGIONS_WITH_CONTENT_RATINGS()
                if self.get_body_class() == x.ratingsbody] +
                list(generic_regions))

    def get_region_slugs(self):
        """Gives us the region slugs that use this rating body."""
        if (waffle.switch_is_active('iarc') and
            self.get_body_class() == mkt.ratingsbodies.GENERIC):
            # For the generic rating body, we just pigeonhole all of the misc.
            # regions into one region slug, GENERIC. Reduces redundancy in the
            # final data structure. Rather than
            # {'pe': {generic_rating}, 'ar': {generic_rating}, etc}, generic
            # regions will just use single {'generic': {generic rating}}
            return [mkt.regions.GENERIC_RATING_REGION_SLUG]
        return [x.slug for x in self.get_regions()]

    def get_body_class(self):
        return mkt.ratingsbodies.RATINGS_BODIES[self.ratings_body]

    def get_body(self):
        """Ratings body instance with translated strings attached."""
        return mkt.ratingsbodies.dehydrate_ratings_body(self.get_body_class())

    def get_rating_class(self):
        return self.get_body_class().ratings[self.rating]

    def get_rating(self):
        """Ratings instance with translated strings attached."""
        return mkt.ratingsbodies.dehydrate_rating(self.get_rating_class())

    def get_label(self):
        """Gives us the name to be used for the form options."""
        return u'%s - %s' % (self.get_body().name, self.get_rating().name)


def update_status_content_ratings(sender, instance, **kw):
    # Flips the app's status from NULL if it has everything else together.
    if (instance.addon.has_incomplete_status() and
        instance.addon.is_fully_complete()):
        instance.addon.update(status=amo.STATUS_PENDING)


models.signals.post_save.connect(update_status_content_ratings,
                                 sender=ContentRating,
                                 dispatch_uid='c_rating_update_app_status')


# The RatingDescriptors table is created with dynamic fields based on
# mkt.constants.ratingdescriptors.
class RatingDescriptors(amo.models.ModelBase, DynamicBoolFieldsMixin):
    """
    A dynamically generated model that contains a set of boolean values
    stating if an app is rated with a particular descriptor.
    """
    addon = models.OneToOneField(Addon, related_name='rating_descriptors')
    field_source = mkt.ratingdescriptors.RATING_DESCS

    class Meta:
        db_table = 'webapps_rating_descriptors'

    def __unicode__(self):
        return u'%s: %s' % (self.id, self.addon.name)

    def iarc_deserialize(self, body=None):
        """Map our descriptor strings back to the IARC ones (comma-sep.)."""
        keys = self.to_keys()
        if body:
            keys = [key for key in keys if body.iarc_name.lower() in key]
        return ', '.join(REVERSE_DESC_MAPPING.get(desc) for desc in keys)

# Add a dynamic field to `RatingDescriptors` model for each rating descriptor.
for k, v in mkt.ratingdescriptors.RATING_DESCS.iteritems():
    field = models.BooleanField(default=False, help_text=v['name'])
    field.contribute_to_class(RatingDescriptors, 'has_%s' % k.lower())


# The RatingInteractives table is created with dynamic fields based on
# mkt.constants.ratinginteractives.
class RatingInteractives(amo.models.ModelBase, DynamicBoolFieldsMixin):
    """
    A dynamically generated model that contains a set of boolean values
    stating if an app features a particular interactive element.
    """
    addon = models.OneToOneField(Addon, related_name='rating_interactives')
    field_source = mkt.ratinginteractives.RATING_INTERACTIVES

    class Meta:
        db_table = 'webapps_rating_interactives'

    def __unicode__(self):
        return u'%s: %s' % (self.id, self.addon.name)

    def iarc_deserialize(self):
        """Map our descriptor strings back to the IARC ones (comma-sep.)."""
        return ', '.join(REVERSE_INTERACTIVES_MAPPING.get(inter)
                         for inter in self.to_keys())


# Add a dynamic field to `RatingInteractives` model for each rating descriptor.
for k, v in mkt.ratinginteractives.RATING_INTERACTIVES.iteritems():
    field = models.BooleanField(default=False, help_text=v['name'])
    field.contribute_to_class(RatingInteractives, 'has_%s' % k.lower())


# The AppFeatures table is created with dynamic fields based on
# mkt.constants.features, which requires some setup work before we call `type`.
class AppFeatures(amo.models.ModelBase, DynamicBoolFieldsMixin):
    """
    A dynamically generated model that contains a set of boolean values
    stating if an app requires a particular feature.
    """
    version = models.OneToOneField(Version, related_name='features')
    field_source = APP_FEATURES

    class Meta:
        db_table = 'addons_features'

    def __unicode__(self):
        return u'Version: %s: %s' % (self.version.id, self.to_signature())

    def set_flags(self, signature):
        """
        Sets flags given the signature.

        This takes the reverse steps in `to_signature` to set the various flags
        given a signature. Boolean math is used since "0.23.1" is a valid
        signature but does not produce a string of required length when doing
        string indexing.
        """
        fields = self._fields()
        # Grab the profile part of the signature and convert to binary string.
        try:
            profile = bin(int(signature.split('.')[0], 16)).lstrip('0b')
            n = len(fields) - 1
            for i, f in enumerate(fields):
                setattr(self, f, bool(int(profile, 2) & 2 ** (n - i)))
        except ValueError as e:
            log.error(u'ValueError converting %s. %s' % (signature, e))

    def to_signature(self):
        """
        This converts the boolean values of the flags to a signature string.

        For example, all the flags in APP_FEATURES order produce a string of
        binary digits that is then converted to a hexadecimal string with the
        length of the features list plus a version appended. E.g.::

            >>> profile = '10001010111111010101011'
            >>> int(profile, 2)
            4554411
            >>> '%x' % int(profile, 2)
            '457eab'
            >>> '%x.%s.%s' % (int(profile, 2), len(profile), 1)
            '457eab.23.1'

        """
        profile = ''.join('1' if getattr(self, f) else '0'
                          for f in self._fields())
        return '%x.%s.%s' % (int(profile, 2), len(profile),
                             settings.APP_FEATURES_VERSION)


# Add a dynamic field to `AppFeatures` model for each buchet feature.
for k, v in APP_FEATURES.iteritems():
    field = models.BooleanField(default=False, help_text=v['name'])
    field.contribute_to_class(AppFeatures, 'has_%s' % k.lower())


class AppManifest(amo.models.ModelBase):
    """
    Storage for manifests.

    Tied to version since they change between versions. This stores both hosted
    and packaged apps manifests for easy access.
    """
    version = models.OneToOneField(Version, related_name='manifest_json')
    manifest = models.TextField()

    class Meta:
        db_table = 'app_manifest'


class RegionListField(json_field.JSONField):
    def to_python(self, value):
        value = super(RegionListField, self).to_python(value)
        if value:
            value = [int(v) for v in value]
        return value


class Geodata(amo.models.ModelBase):
    """TODO: Forgo AER and use bool columns for every region and carrier."""
    addon = models.OneToOneField('addons.Addon', related_name='_geodata')
    restricted = models.BooleanField(default=False)
    popular_region = models.CharField(max_length=10, null=True)
    banner_regions = RegionListField(default=None, null=True)
    banner_message = PurifiedField()
    # Exclude apps with USK_RATING_REFUSED in Germany.
    region_de_usk_exclude = models.BooleanField()

    class Meta:
        db_table = 'webapps_geodata'

    def __unicode__(self):
        return u'%s (%s): <Webapp %s>' % (
            self.id, 'restricted' if self.restricted else 'unrestricted',
            self.addon.id)

    def get_status(self, region):
        """
        Return the status of listing in a given region (e.g., China).
        """
        return getattr(self, 'region_%s_status' % parse_region(region).slug,
                       amo.STATUS_PUBLIC)

    def set_status(self, region, status, save=False):
        """Return a tuple of `(value, changed)`."""

        value, changed = None, False

        attr = 'region_%s_status' % parse_region(region).slug
        if hasattr(self, attr):
            value = setattr(self, attr, status)

            if self.get_status(region) != value:
                changed = True
                # Save only if the value is different.
                if save:
                    self.save()

        return None, changed

    def get_status_slug(self, region):
        return {
            amo.STATUS_PENDING: 'pending',
            amo.STATUS_PUBLIC: 'public',
            amo.STATUS_REJECTED: 'rejected',
        }.get(self.get_status(region), 'unavailable')

    @classmethod
    def get_status_messages(cls):
        return {
            # L10n: An app is awaiting approval for a particular region.
            'pending': _('awaiting approval'),
            # L10n: An app is rejected for a particular region.
            'rejected': _('rejected'),
            # L10n: An app requires additional review for a particular region.
            'unavailable': _('requires additional review')
        }

    def banner_regions_names(self):
        if self.banner_regions is None:
            return []
        return sorted(unicode(mkt.regions.REGIONS_CHOICES_ID_DICT.get(k).name)
                      for k in self.banner_regions)

    def banner_regions_slugs(self):
        if self.banner_regions is None:
            return []
        return sorted(unicode(mkt.regions.REGIONS_CHOICES_ID_DICT.get(k).slug)
                      for k in self.banner_regions)

    def get_nominated_date(self, region):
        """
        Return the timestamp of when the app was approved in a region.
        """
        return getattr(self,
                       'region_%s_nominated' % parse_region(region).slug)

    def set_nominated_date(self, region, timestamp=None, save=False):
        """Return a tuple of `(value, saved)`."""

        value, changed = None, False

        attr = 'region_%s_nominated' % parse_region(region).slug
        if hasattr(self, attr):
            if timestamp is None:
                timestamp = datetime.datetime.now()
            value = setattr(self, attr, timestamp)

            if self.get_nominated_date(region) != value:
                changed = True
                # Save only if the value is different.
                if save:
                    self.save()

        return None, changed


# (1) Add a dynamic status field to `Geodata` model for each special region:
# -  0: STATUS_NULL (Unavailable)
# -  2: STATUS_PENDING (Pending)
# -  4: STATUS_PUBLIC (Public)
# - 12: STATUS_REJECTED (Rejected)
#
# (2) Add a dynamic nominated field to keep track of timestamp for when
# the developer requested approval for each region.
for region in mkt.regions.SPECIAL_REGIONS:
    help_text = _('{region} approval status').format(region=region.name)
    field = models.PositiveIntegerField(help_text=help_text,
        choices=amo.MKT_STATUS_CHOICES.items(), db_index=True, default=0)
    field.contribute_to_class(Geodata, 'region_%s_status' % region.slug)

    help_text = _('{region} nomination date').format(region=region.name)
    field = models.DateTimeField(help_text=help_text, null=True)
    field.contribute_to_class(Geodata, 'region_%s_nominated' % region.slug)

# Add a dynamic field to `Geodata` model to exclude pre-IARC public unrated
# Brazil and Germany games.
for region in (mkt.regions.BR, mkt.regions.DE):
    field = models.BooleanField(default=False)
    field.contribute_to_class(Geodata, 'region_%s_iarc_exclude' % region.slug)

# Save geodata translations when a Geodata instance is saved.
models.signals.pre_save.connect(save_signal, sender=Geodata,
                                dispatch_uid='geodata_translations')
