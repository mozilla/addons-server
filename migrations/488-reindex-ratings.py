#!/usr/bin/env python

from amo.utils import chunked

from addons.models import Addon


def run():
    """Fix app ratings in ES (bug 787162)."""
    for chunk in chunked(Addon.objects.filter(total_reviews__gt=0), 50):
        for addon in chunk:
            # Emit post-save signals so ES gets the correct bayesian ratings.
            # One review is enough to fire off the tasks.
            try:
                addon.reviews[0].save()
            except IndexError:
                # It's possible that `total_reviews` is a liar.
                print '- No reviews found for %s ...' % addon
