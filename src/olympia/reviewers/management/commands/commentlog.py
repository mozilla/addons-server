from django.core.management.base import BaseCommand

from olympia.activity.models import ActivityLog
from olympia.amo.utils import chunked
from olympia.reviewers.tasks import add_commentlog


class Command(BaseCommand):
    help = 'Add a CommentLog entry for all ActivityLog items'

    def handle(self, *args, **options):
        pks = (
            ActivityLog.objects.review_queue()
            .values_list('pk', flat=True)
            .order_by('id')
        )

        for chunk in chunked(pks, 100):
            add_commentlog.delay(chunk)
