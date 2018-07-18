#!/usr/bin/env python

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError

import mkt

from mkt.developers.cron import exclude_new_region
from mkt.webapps.models import AddonExcludedRegion
from mkt.zadmin.models import FeaturedAppRegion


def run():
    """
    Migrate from New Mexico to Old Mexico. Then add AddonExcludedRegion
    objects for those apps that opted out of being added to new regions.
    """

    # There were two Mexicos (12 is the first; 18 was the second one).
    for aer in AddonExcludedRegion.objects.filter(region=18):
        try:
            aer.update(region=mkt.regions.MX.id)
            print('OK: %s New Mexico -> Old Mexico' % aer.id)
        except (IntegrityError, ObjectDoesNotExist):
            print('SKIP: %s New Mexico -> Old Mexico' % aer.id)

    # And the featured apps, if there were any.
    for far in FeaturedAppRegion.objects.filter(region=18):
        try:
            far.update(region=mkt.regions.MX.id)
            print('OK: %s New Mexico -> Old Mexico' % far.id)
        except (IntegrityError, ObjectDoesNotExist):
            print('SKIP: %s New Mexico -> Old Mexico' % far.id)

    # New regions were added.
    exclude_new_region(
        [
            mkt.regions.MX,
            mkt.regions.HU,
            mkt.regions.DE,
            mkt.regions.ME,
            mkt.regions.RS,
            mkt.regions.GR,
        ]
    )
