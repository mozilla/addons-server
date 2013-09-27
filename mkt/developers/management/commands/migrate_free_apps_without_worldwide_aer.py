import logging

from django.core.management.base import NoArgsCommand

import amo
from mkt.constants.regions import WORLDWIDE

log = logging.getLogger('z.task')


class Command(NoArgsCommand):
    help = 'Migrate free apps without a world AER to enable_new_regions=True.'

    def handle_noargs(self, *args, **options):
        # Avoid import error.
        from mkt.webapps.models import AddonExcludedRegion as AER, Webapp

        # First exclude apps that have opted out of enabling new regions.
        excludes = (AER.objects.filter(region=WORLDWIDE.id)
                               .values_list('addon', flat=True))

        qs = (Webapp.objects.filter(premium_type=amo.ADDON_FREE)
                            .exclude(id__in=excludes))
        # Now update the relevant apps.
        for app in qs.iterator():
            log.info('[App %s] Updated to have '
                     'enable_new_regions=True' % app.pk)
            app.update(enable_new_regions=True)
