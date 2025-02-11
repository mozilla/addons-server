from django.core.management.base import BaseCommand

from olympia.promoted.models import (
    PromotedAddon,
    PromotedApproval,
)


class Command(BaseCommand):
    help = 'Sync promoted addons to or from the new models'

    def sync_forward(self):
        for instance in PromotedAddon.objects.iterator():
            # Do not set a due date or trigger any actual changes.
            instance.save(_due_date=None, update_fields=[])

        for instance in PromotedApproval.objects.iterator():
            instance.save(update_fields=[])

    def handle(self, *args, **options):
        self.stdout.write('Syncing promoted addons')
        self.sync_forward()
