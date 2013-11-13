import logging

from django.core.management.base import BaseCommand, CommandError

log = logging.getLogger('z.task')


class Command(BaseCommand):
    help = ('Exclude apps in a given region. Syntax: \n'
            '    ./manage.py exclude_region <region_slug>')

    def handle(self, *args, **options):
        # Avoid import error.
        from mkt.regions.utils import parse_region
        from mkt.webapps.models import Webapp

        try:
            region_slug = args[0]
        except IndexError:
            raise CommandError(self.help)

        region = parse_region(region_slug)

        for app in Webapp.objects.all():
            aer, created = app.addonexcludedregion.get_or_create(
                region=region.id)
            if created:
                log.info('[App %s - %s] Excluded in region %r'
                         % (app.pk, app.slug, region.slug))
