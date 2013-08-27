import logging

from django.core.management.base import BaseCommand

import amo
from addons.models import Addon
from versions.models import Version


log = logging.getLogger('z.addons')


class Command(BaseCommand):
    help = 'Creates current_version\'s for themes that are missing them.'

    def handle(self, *args, **options):
        for addon in Addon.objects.filter(type=amo.ADDON_PERSONA,
                                          _current_version__isnull=True):
            if addon._latest_version:
                addon.update(_current_version=addon._latest_version,
                             _signal=False)
            else:
                version = Version.objects.create(addon=addon, version='0')
                addon.update(_current_version=version, _signal=False)
            log.info('Fixed missing current version for add-on %s' % addon.id)
