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
        from mkt.webapps.models import AddonExcludedRegion as AER, Webapp

        try:
            region_id = args[0]
        except IndexError:
            raise CommandError(self.help)

        if region_id.isdigit():
            # We got an ID, so get the slug.
            region = mkt.regions.REGIONS_CHOICES_ID_DICT[int(region_id)]
        else:
            # We got a slug, so get the ID.
            region = mkt.regions.REGIONS_DICT[region_id]

        region = mkt.regions.REGIONS_DICT[region_id]

        games = Webapp.objects.filter(category__type=amo.ADDON_WEBAPP,
            category__slug='games')

        for app in games:
            if region.ratingsbodies and not app.content_ratings_in(region):
                AER.objects.get_or_create(addon=app, region=region.id)
                log.info('[App %s - %s] Excluded in region %r'
                         % (app.pk, app.slug, region.slug))
