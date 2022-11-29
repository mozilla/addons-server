from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.activity.tasks import create_ratinglog
from olympia.amo.celery import create_chunked_tasks_signatures


log = olympia.core.logger.getLogger('z.amo.activity')


class Command(BaseCommand):
    help = 'Backfill the RatingLog model table with historic Ratings.'
    rating_actions = (
        amo.LOG.ADD_RATING.id,
        amo.LOG.APPROVE_RATING.id,
        amo.LOG.DELETE_RATING.id,
        amo.LOG.EDIT_RATING.id,
    )

    def handle(self, *args, **options):
        alog_ids = ActivityLog.objects.filter(
            action__in=self.rating_actions
        ).values_list('id', flat=True)
        create_chunked_tasks_signatures(create_ratinglog, alog_ids, 100).apply_async()
