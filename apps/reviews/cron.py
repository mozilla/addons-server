import logging

from celery.messaging import establish_connection

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
    with establish_connection() as conn:
        for chunk in chunked(pairs, 50):
            tasks.update_denorm.apply_async(args=chunk, connection=conn)


@cronjobs.register
def addon_reviews_ratings():
    """Update all add-on total_reviews and average/bayesian ratings."""
    addons = Addon.objects.values_list('id', flat=True)
    with establish_connection() as conn:
        for chunk in chunked(addons, 100):
            tasks.cron_review_aggregate.apply_async(args=chunk,
                                                    connection=conn)
