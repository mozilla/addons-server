from django.conf import settings
from django.core.management.base import BaseCommand

from olympia import amo
from olympia.addons.models import Addon
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.amo.decorators import use_primary_db
from olympia.promoted.models import (
    PromotedAddon,
)
from olympia.users.models import UserProfile


class Command(BaseCommand):
    help = 'Give themes with Firefox as author the "By Firefox" badge'

    @use_primary_db
    def handle(self, *args, **options):
        firefox_user = UserProfile.objects.get(pk=settings.TASK_USER_ID)
        addons = (
            Addon.objects.public()
            .filter(type=amo.ADDON_STATICTHEME, authors=firefox_user)
            .no_transforms()
        )
        for addon in addons:
            self.stdout.write(f'Promoting {addon.slug}')
            promotion, created = PromotedAddon.objects.get_or_create(
                addon=addon,
                defaults={
                    'application_id': amo.FIREFOX.id,
                    'group_id': PROMOTED_GROUP_CHOICES.LINE,
                },
            )
            promotion.approve_for_addon()
