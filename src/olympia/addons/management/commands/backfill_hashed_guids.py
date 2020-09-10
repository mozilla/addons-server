from django.core.management.base import BaseCommand

from olympia.addons.models import AddonGUID
from olympia.addons.tasks import backfill_hashed_guids
from olympia.amo.celery import create_chunked_tasks_signatures


class Command(BaseCommand):
    help = 'Compute a hashed GUID for all AddonGUID entries without one.'

    def handle(self, *args, **options):
        ids = AddonGUID.objects.filter(hashed_guid=None).values_list(
            'id', flat=True
        )
        chunked_tasks = create_chunked_tasks_signatures(
            backfill_hashed_guids, items=list(ids), chunk_size=100
        )
        chunked_tasks.apply_async()
