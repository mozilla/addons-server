from django.conf import settings
from django.core.management.base import BaseCommand

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.decorators import use_primary_db
from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.promoted.models import PromotedAddon, PromotedGroup
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
            group = PromotedGroup.objects.get(group_id=PROMOTED_GROUP_CHOICES.LINE)
            PromotedAddon.objects.get_or_create(
                addon=addon,
                application_id=amo.FIREFOX.id,
                promoted_group=group,
            )
            addon.approve_for_version(promoted_groups=[group])
