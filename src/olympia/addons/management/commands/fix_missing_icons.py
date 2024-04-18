from django.core.files.storage import default_storage as storage
from django.core.management.base import BaseCommand

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.tasks import resize_icon
from olympia.core.logger import getLogger


log = getLogger('z.addons.fix_missing_icons')


class Command(BaseCommand):
    help = 'Fix missing icons on specific add-ons'
    addon_ids = [271830, 823490, 805933, 583250, 790974, 3006]

    def handle(self, *args, **options):
        for addon in Addon.objects.filter(pk__in=self.addon_ids):
            icon_path = addon.get_icon_path('original')
            if storage.exists(icon_path):
                log.info(
                    'Original icon already exists for addon %s, skipping.', addon.pk
                )
                continue
            backup_path = f'static/img/addon-icons/{addon.pk}-64.png'
            with open(backup_path, 'rb') as f:
                storage.save(storage.path(icon_path), f)
            resize_icon.delay(
                icon_path,
                addon.pk,
                amo.ADDON_ICON_SIZES,
                set_modified_on=addon.serializable_reference(),
            )
            log.info(
                'Saved new original icon for addon %s and triggered resizing.', addon.pk
            )
