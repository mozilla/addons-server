#!/usr/bin/env python

from celeryutils import task

from amo.utils import chunked
from amo.decorators import write

from addons.models import Addon


@task
@write
def reindex_reviews(addon_id, **kw):
    try:
        # Emit post-save signals so ES gets the correct bayesian ratings.
        # One review is enough to fire off the tasks.
        Addon.objects.get(id=addon_id).reviews[0].save()
    except IndexError:
        # It's possible that `total_ratings` was wrong.
        print 'No reviews found for %s' % addon_id


def run():
    """Fix app ratings in ES (bug 787162)."""
    ids = (Addon.objects.filter(total_ratings__gt=0)
           .values_list('id', flat=True))
    for chunk in chunked(ids, 50):
        [reindex_reviews.delay(pk) for pk in chunk]
