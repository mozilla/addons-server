import datetime

from django.db import models
from django.db.models.loading import get_model

import waffle

from addons.models import Category

import amo
import mkt
import mkt.regions
from mkt.carriers import get_carrier


class FeaturedAppQuerySet(models.query.QuerySet):
    """
    Custom QuerySet that encapsulates common filtering logic used when
    querying QuerySets of FeaturedApp instances.

    This QuerySet is implemented by FeaturedAppManager, which attempts to
    check this class' attributes when its own __getattr__ method raises an
    AttributeError.
    """

    def featured(self, cat=None, region=None, limit=6, mobile=False,
                 gaia=False, tablet=False):
        """
        Filters the QuerySet, removing FeaturedApp instances that should
        not be featured based on the passed criteria.

        If a region is defined and there are fewer than `limit` items
        remaining in the resultant queryset, the difference is populated by
        additional apps that are featured worldwide.
        """
        qs = self.active()
        Webapp = get_model('webapps', 'Webapp')

        excluded = Webapp.objects.none()
        if region:
            excluded = Webapp.get_excluded_in(region)

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
        category. The passed category can be either a Category instance
        or a list of Category instances.
        """
        if isinstance(category, list):
            return self.filter(category__in=category)
        return self.filter(category=category.id if category else None)


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
