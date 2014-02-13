import logging

from django.core.management.base import BaseCommand

import amo
from mkt.constants.regions import (REGIONS_CHOICES_ID_DICT,
                                   SPECIAL_REGION_IDS)

log = logging.getLogger('z.task')


class Command(BaseCommand):
    """
    Backfill Webapp Geodata by inferring regional popularity from
    AddonExcludedRegion objects (or lack thereof).
    Remove AddonExcludedRegion objects for free apps.
    """

    def handle(self, *args, **options):
        from mkt.webapps.models import Webapp

        paid_types = amo.ADDON_PREMIUMS + (amo.ADDON_FREE_INAPP,)

        apps = Webapp.objects.all()
        for app in apps:
            # If it's already restricted, don't bother.
            if app.geodata.restricted:
                continue

            geodata = {}

            # If this app was excluded in every region except one,
            # let's consider it regionally popular in that particular region.
            region_ids = app.get_region_ids()
            if len(region_ids) == 1:
                geodata['popular_region'] = (
                    REGIONS_CHOICES_ID_DICT[region_ids[0]].slug
                )

            if app.premium_type in paid_types:
                geodata['restricted'] = True
            else:
                exclusions = app.addonexcludedregion.exclude(
                    region__in=SPECIAL_REGION_IDS)
                for exclusion in exclusions:
                    log.info('[App %s - %s] Removed exclusion: %s'
                             % (app.pk, app.slug, exclusion))

                    # Remove all other existing exclusions, since all apps
                    # are public in every region by default. If developers
                    # want to hard-restrict their apps they can now do that.
                    exclusion.delete()

            app.geodata.update(**geodata)
