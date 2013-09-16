from django.core.management.base import BaseCommand

import amo
from addons.models import AddonPremium


class Command(BaseCommand):
    help = 'Clean up existing AddonPremium objects for free apps.'

    def handle(self, *args, **options):
        (AddonPremium.objects.filter(addon__premium_type__in=amo.ADDON_FREES)
                             .delete())
