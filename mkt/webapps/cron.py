from datetime import datetime, timedelta

from django.db.models import Count

import cronjobs
from celery.task.sets import TaskSet

import amo
from amo.utils import chunked

from .models import Installed
from .tasks import webapp_update_weekly_downloads


@cronjobs.register
def update_weekly_downloads():
    """Update the weekly "downloads" from the users_install table."""
    interval = datetime.today() - timedelta(days=7)
    counts = (Installed.objects.values('addon')
                               .filter(created__gte=interval,
                                       addon__type=amo.ADDON_WEBAPP)
                               .annotate(count=Count('addon')))

    ts = [webapp_update_weekly_downloads.subtask(args=[chunk])
          for chunk in chunked(counts, 1000)]
    TaskSet(ts).apply_async()
