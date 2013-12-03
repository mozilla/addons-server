import logging

from django.core.management.base import BaseCommand

import amo
from mkt.constants.regions import (ALL_REGIONS_WITH_CONTENT_RATINGS,
                                   REGIONS_CHOICES_ID_DICT)

log = logging.getLogger('z.task')


class Command(BaseCommand):
    """
    Backfill Webapp Geodata by inferring regional popularity from
    AddonExcludedRegion objects (or lack thereof).
    Remove AddonExcludedRegion objects for free apps (except unrated games).
    """

    def handle(self, *args, **options):
        from mkt.webapps.models import Webapp

        paid_types = amo.ADDON_PREMIUMS + (amo.ADDON_FREE_INAPP,)

        games_cat = Webapp.category('games')
        content_region_ids = [x.id for x in ALL_REGIONS_WITH_CONTENT_RATINGS()]

        apps = Webapp.objects.all()
        for app in apps:
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
                for exclusion in app.addonexcludedregion.all():
                    # Do not delete region exclusions meant for unrated games.
                    region = REGIONS_CHOICES_ID_DICT[exclusion.region]
                    if (games_cat and region.id in content_region_ids and
                        app.listed_in(category='games') and
                        not app.content_ratings_in(region)):
                        continue

                    log.info('[App %s - %s] Removed exclusion: %s'
                             % (app.pk, app.slug, exclusion))

                    # Remove all other existing exclusions, since all apps
                    # are public in every region by default. If developers
                    # want to hard-restrict their apps they can now do that.
                    exclusion.delete()

            app.geodata.update(**geodata)
