from django.core.management.base import BaseCommand
from django.db.models.signals import post_save

from olympia.promoted.models import (
    PromotedAddon,
    PromotedApproval,
)


class Command(BaseCommand):
    help = 'Sync promoted addons to or from the new models'

    def send_post_save(self, model, instance):
        self.stdout.write(f'post_save.send(sender={model}, instance={instance})')
        post_save.send(sender=model, instance=instance)

    def sync_forward(self):
        for instance in PromotedAddon.objects.iterator():
            self.send_post_save(PromotedAddon, instance)

        for instance in PromotedApproval.objects.iterator():
            self.send_post_save(PromotedApproval, instance)

    def handle(self, *args, **options):
        self.stdout.write('Syncing promoted addons')
        self.sync_forward()
