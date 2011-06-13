import logging

from celery.task.sets import TaskSet

import cronjobs
from amo.utils import chunked
from addons.models import Addon

from . import tasks
from .models import Review

log = logging.getLogger('z.cron')


@cronjobs.register
def reviews_denorm():
    """Set is_latest and previous_count for all reviews."""
    pairs = list(set(Review.objects.values_list('addon', 'user')))
    ts = [tasks.update_denorm.subtask(args=chunk)
          for chunk in chunked(pairs, 50)]
    TaskSet(ts).apply_async()


@cronjobs.register
def addon_reviews_ratings():
    """Update all add-on total_reviews and average/bayesian ratings."""
    addons = Addon.objects.values_list('id', flat=True)
    ts = [tasks.cron_review_aggregate.subtask(args=chunk)
          for chunk in chunked(addons, 100)]
    TaskSet(ts).apply_async()
