import logging

from django.core.management.base import BaseCommand, CommandError

import amo

import mkt

log = logging.getLogger('z.task')


class Command(BaseCommand):
    help = ('Exclude unrated games in a given region. Syntax: \n'
            '    ./manage.py exclude_games <region_slug>')

    def handle(self, *args, **options):
        # Avoid import error.
        from mkt.webapps.models import Webapp

        try:
            region_slug = args[0]
        except IndexError:
            raise CommandError(self.help)

        region = mkt.regions.REGIONS_DICT[region_slug]

        games = Webapp.objects.filter(category__type=amo.ADDON_WEBAPP,
            category__slug='games')

        german_bodies = (mkt.ratingsbodies.USK.id,
                         mkt.ratingsbodies.GENERIC.id)
        for app in games:
            if (region == mkt.regions.DE and app.content_ratings.filter(
                ratings_body__in=german_bodies).exists()):
                # Special case for Germany, allow to be listed if have USK or
                # Generic.
                continue

            elif region.ratingsbody and not app.content_ratings_in(region):
                aer, created = app.addonexcludedregion.get_or_create(
                    region=region.id)
                if created:
                    log.info('[App %s - %s] Excluded in region %r'
                             % (app.pk, app.slug, region.slug))
