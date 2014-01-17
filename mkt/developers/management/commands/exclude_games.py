import logging

from django.core.management.base import BaseCommand

import amo

import mkt


log = logging.getLogger('z.task')


class Command(BaseCommand):
    help = ('Exclude pre-IARC unrated public games in Brazil/Germany.')

    def handle(self, *args, **options):
        # Avoid import error.
        from mkt.webapps.models import Geodata, Webapp

        games = Webapp.objects.filter(
            category__type=amo.ADDON_WEBAPP, category__slug='games',
            status__in=(amo.STATUS_PUBLIC, amo.STATUS_PUBLIC_WAITING))

        for app in games:
            save = False
            geodata, c = Geodata.objects.safer_get_or_create(addon=app)

            # Germany.
            german_bodies = (mkt.ratingsbodies.USK.id,
                             mkt.ratingsbodies.GENERIC.id)
            if (not app.content_ratings.filter(
                ratings_body__in=german_bodies).exists()):
                save = True
                geodata.region_de_iarc_exclude = True
                log.info('[App %s - %s] Excluded in region de'
                         % (app.pk, app.slug))

            # Brazil.
            if (not app.content_ratings.filter(
                ratings_body=mkt.ratingsbodies.CLASSIND.id).exists()):
                save = True
                geodata.region_br_iarc_exclude = True
                log.info('[App %s - %s] Excluded in region br'
                         % (app.pk, app.slug))

            if save:
                geodata.save()
