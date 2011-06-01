from django.core.management.base import BaseCommand

from addons.models import Addon
from amo.utils import chunked
from devhub.models import ActivityLog
from editors.tasks import add_versionlog

from celery.messaging import establish_connection


class Command(BaseCommand):
    help = 'Add a VersionLog entry for all ActivityLog items'

    def handle(self, *args, **options):
        pks = (ActivityLog.objects.review_queue().values_list('pk', flat=True)
                                  .order_by('id'))

        with establish_connection():
            for chunk in chunked(pks, 100):
                add_versionlog.delay(chunk)
