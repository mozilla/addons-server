from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia.abuse.tasks import sync_cinder_policies


class Command(BaseCommand):
    log = olympia.core.logger.getLogger('z.abuse')

    def handle(self, *args, **options):
        sync_cinder_policies()

        self.log.info('Triggered policy sync task.')
