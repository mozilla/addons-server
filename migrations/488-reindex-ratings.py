from amo.utils import chunked

from reviews.models import Review


def run():
    """Fix app ratings in ES (bug 787162)."""
    for chunk in chunked(Review.objects.all(), 50):
        # Emit post-save signals so ES gets the correct bayesian ratings.
        [review.save() for review in chunk]
