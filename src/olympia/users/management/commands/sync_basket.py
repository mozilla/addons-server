from django.core.management.base import BaseCommand

from olympia import amo
from olympia.addons.models import AddonUser
from olympia.users.tasks import sync_user_with_basket


class Command(BaseCommand):
    """Syncronize our user notifications with basket.

    This should not be needed for regular use and is primarily
    used for the initial sync between AMO and basket"""
    help = 'Syncronize our user notifications with basket..'

    def handle(self, *args, **options):
        developers = AddonUser.objects.exclude(
            addon__status=amo.STATUS_DELETED).values_list('user_id', flat=True)

        for developer_id in developers:
            sync_user_with_basket.delay(developer_id)

        self.stdout.write(
            'Synchronizing %s developers with basket now' % len(developers))
