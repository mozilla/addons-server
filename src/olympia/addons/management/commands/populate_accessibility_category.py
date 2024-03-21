from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.addons.models import Addon
from olympia.constants.base import ADDON_EXTENSION
from olympia.constants.categories import CATEGORIES


log = olympia.core.logger.getLogger('z.addons.populate_accessibility_category')

guids = [
    'addon@darkreader.org',
    '{830f38bd-efc5-45dc-a5a6-064d9a638806}',
    'jid1-QoFqdK4qzUfGWQ@jetpack',
    '{ddc62400-f22d-4dd3-8b4a-05837de53c2e}',
    'addon@rao-text-to-speech.com',
    '@mobiledyslexic',
    '{759dbb01-b646-4327-bf9e-69ca2543ef8d}',
    'zoompage-we@DW-dev',
    'axSHammer@jantrid.net',
    'tabswitcher@volinsky.net',
    'superstop@gavinsharp.com',
    'tab-mover@code.guido-berhoerster.org',
    '{c2ecdf60-7077-4bfa-b9c2-4892a8ded8c6}',
    '{3c078156-979c-498b-8990-85f7987dd929}',
]


class Command(BaseCommand):
    help = 'Populate accessibility category with some pre-determined add-ons'

    def add_addons_to_category(self, new_category):
        for addon in Addon.objects.filter(guid__in=guids):
            addon.set_categories(addon.all_categories + [new_category])
            log.info('Added addon %s to %s category.', addon, new_category)
        log.info('Done adding add-ons to %s category', new_category)

    def handle(self, *args, **kwargs):
        self.add_addons_to_category(CATEGORIES[ADDON_EXTENSION]['accessibility'])
