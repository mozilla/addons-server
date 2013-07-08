import datetime

from django.core.cache import cache
from django.db import models
from django.db.models.loading import get_model

import waffle

from addons.models import Category

import amo
import mkt
import mkt.regions
from mkt.carriers import get_carrier, get_carrier_id


class FeaturedAppQuerySet(models.query.QuerySet):
    """
    Custom QuerySet that encapsulates common filtering logic used when
    querying QuerySets of FeaturedApp instances.

    This QuerySet is implemented by FeaturedAppManager, which attempts to
    check this class' attributes when its own __getattr__ method raises an
    AttributeError.
    """

    def featured(self, cat=None, region=None, limit=9, mobile=False,
                 gaia=False, tablet=False, profile=None):
        """
        Filters the QuerySet, removing FeaturedApp instances that should
        not be featured based on the passed criteria.

        If a region is defined and there are fewer than `limit` items
        remaining in the resultant queryset, the difference is populated by
        additional apps that are featured worldwide.

        If `profile` (a FeatureProfile object) is provided we filter by the
        profile. If you don't want to filter by these don't pass it. I.e. do
        the device detection for when this happens elsewhere.

        """
        qs = self.active()
        Webapp = get_model('webapps', 'Webapp')

        excluded = Webapp.objects.none()
        if region:
            from mkt.webapps.models import get_excluded_in
            excluded = get_excluded_in(region.id)

        if waffle.switch_is_active('disabled-payments') or not gaia:
            qs = qs.filter(app__premium_type__in=amo.ADDON_FREES)

        qs = qs.for_category(cat)

        carrier = get_carrier()
        if carrier:
            qs = qs.for_carrier(carrier)

        if gaia:
            qs = qs.gaia()
        elif mobile:
            qs = qs.mobile()

        if tablet:
            qs = qs.tablet()

        if profile and waffle.switch_is_active('buchets'):
            # Exclude apps that require any features we don't support.
            qs = qs.filter(**profile.to_kwargs(
                prefix='app___current_version__features__has_'))

        qs_pre_region = qs._clone()

        if region:
            qs = qs.for_region(region).exclude(app__id__in=excluded)

            # Fill the empty spots with Worldwide-featured apps.
            if limit:
                empty_spots = limit - qs.count()
                if empty_spots > 0 and region != mkt.regions.WORLDWIDE:
                    qs |= (qs_pre_region.worldwide()
                           .exclude(id__in=[x.id for x in qs])
                           .exclude(app__id__in=excluded))

        if limit:
            qs = qs[:limit]

        return qs

    def featured_ids(self, cat=None, region=None, profile=None):

        carrier = get_carrier_id()
        cache_key = 'featured:%s:%s:%s:%s' % (
            region.id if region else 0,
            cat.id if cat else 0,
            profile.to_signature() if profile else 0,
            carrier if carrier else 0)

        val = cache.get(cache_key)
        if val is not None:
            return val

        val = self.featured(cat=cat, region=region,
                            profile=profile).values_list('app_id', flat=True)
        cache.set(cache_key, val, 60 * 60)
        return val

    def active(self):
        """
        Convenience method that bundles self.active_date and self.public
        in a single call.
        """
        return self.active_date().public()

    def active_date(self):
        """
        Removes features in the queryset whose start/end dates render the
        feature inactive.
        """
        now = datetime.date.today()
        qs = (self.filter(start_date__lte=now) |
              self.filter(start_date__isnull=True))
        qs = (qs.filter(end_date__gte=now) |
              qs.filter(end_date__isnull=True))
        return qs

    def public(self):
        """
        Removes features in the queryset that are neither public nor
        disabled by its owner.
        """
        return self.filter(app__status=amo.STATUS_PUBLIC,
                           app__disabled_by_user=False)

    def gaia(self):
        """
        Removes features in the queryset that are not available for Gaia.
        """
        return self.filter(
            app__addondevicetype__device_type=amo.DEVICE_GAIA.id)

    def mobile(self):
        """
        Removes features in the queryset that are not available for mobile
        devices.
        """
        return self.filter(
            app__addondevicetype__device_type=amo.DEVICE_MOBILE.id)

    def tablet(self):
        """
        Removes features in the queryset that are not available for tablet
        devices.
        """
        return self.filter(
            app__addondevicetype__device_type=amo.DEVICE_TABLET.id)

    def for_carrier(self, carrier):
        """
        Removes features in the queryset that are not available for the
        passed carrier.
        """
        return self.filter(carriers__carrier=carrier)

    def for_region(self, region):
        """
        Removes features in the queryset that are not available for the
        passed region.
        """
        return self.filter(regions__region=region.id)

    def worldwide(self):
        """
        Removes features in the queryset that are not available
        worldwide.
        """
        return self.filter(regions__region=mkt.regions.WORLDWIDE.id)

    def for_category(self, category):
        """
        Removes features in the queryset that are not in the passed
        category. The passed category is a Category instance.
        """
        if category:
            return self.filter(category=category.id)
        return self


class FeaturedAppManager(amo.models.ManagerBase):
    """
    Custom manager that implements FeaturedAppQuerySet on all querysets for
    the model.

    If a nonexistent attribute is accessed on this manager, FeaturedAppQuerySet
    is also checked and is returned if it exists. This allows DRY definition of
    filtration methods that can be accessed both on the QuerySet or on the
    manager.
    """
    def __getattr__(self, attr, *args):
        try:
            return getattr(self.__class__, attr, *args)
        except AttributeError, orig:
            # The attribute attempting to be accessed doesn't exist on the
            # manager. Let's see if it exists on the QuerySet.
            try:
                return getattr(self.get_query_set(), attr, *args)
            except AttributeError:
                # If it doesn't exist on the QuerySet either, reraise the
                # original exception.
                raise orig

    def get_query_set(self):
        return FeaturedAppQuerySet(self.model).exclude(
            app__status=amo.STATUS_DELETED)


class FeaturedApp(amo.models.ModelBase):
    app = models.ForeignKey('webapps.Webapp', null=False)
    category = models.ForeignKey(Category, null=True)
    is_sponsor = models.BooleanField(default=False)
    start_date = models.DateField(null=True)
    end_date = models.DateField(null=True)

    objects = FeaturedAppManager()

    class Meta:
        db_table = 'zadmin_featuredapp'


class FeaturedAppRegion(amo.models.ModelBase):
    featured_app = models.ForeignKey(FeaturedApp, null=False,
                                     related_name='regions')
    region = models.PositiveIntegerField(default=mkt.regions.WORLDWIDE.id,
                                         db_index=True)


class FeaturedAppCarrier(amo.models.ModelBase):
    featured_app = models.ForeignKey(FeaturedApp, null=False,
                                     related_name='carriers')
    carrier = models.CharField(max_length=255, db_index=True, null=False)
