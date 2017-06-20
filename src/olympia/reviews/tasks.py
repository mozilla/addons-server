from django.db.models import Count, Avg, F

import caching.base as caching

import olympia.core.logger
from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import write

from .models import Review, GroupedRating

log = olympia.core.logger.getLogger('z.task')


@task(rate_limit='50/m')
@write
def update_denorm(*pairs, **kw):
    """
    Takes a bunch of (addon, user) pairs and sets the denormalized fields for
    all reviews matching that pair.
    """
    log.info('[%s@%s] Updating review denorms.' %
             (len(pairs), update_denorm.rate_limit))
    for addon, user in pairs:
        reviews = list(Review.without_replies.all().no_cache()
                       .filter(addon=addon, user=user).order_by('created'))
        if not reviews:
            continue

        for idx, review in enumerate(reviews):
            review.previous_count = idx
            review.is_latest = False
        reviews[-1].is_latest = True

        for review in reviews:
            review.save()


@task
@write
def addon_review_aggregates(addons, **kw):
    if isinstance(addons, (int, long)):  # Got passed a single addon id.
        addons = [addons]
    log.info('[%s@%s] Updating total reviews and average ratings.' %
             (len(addons), addon_review_aggregates.rate_limit))
    addon_objs = list(Addon.objects.filter(pk__in=addons))
    # The following returns something like
    # [{'rating': 2.0, 'addon': 7L, 'count': 5},
    #  {'rating': 3.75, 'addon': 6L, 'count': 8}, ...]
    qs = (Review.without_replies.all().no_cache()
          .filter(addon__in=addons, is_latest=True)
          .values('addon')  # Group by addon id.
          .annotate(rating=Avg('rating'), count=Count('addon'))  # Aggregates.
          .order_by())  # Reset order by so that `created` is not included.
    stats = {x['addon']: (x['rating'], x['count']) for x in qs}
    for addon in addon_objs:
        rating, reviews = stats.get(addon.id, [0, 0])
        addon.update(total_reviews=reviews, average_rating=rating)

    # Delay bayesian calculations to avoid slave lag.
    addon_bayesian_rating.apply_async(args=addons, countdown=5)
    addon_grouped_rating.apply_async(args=addons)


@task
@write
def addon_bayesian_rating(*addons, **kw):
    def addon_aggregates():
        return Addon.objects.valid().aggregate(rating=Avg('average_rating'),
                                               reviews=Avg('total_reviews'))

    log.info('[%s@%s] Updating bayesian ratings.' %
             (len(addons), addon_bayesian_rating.rate_limit))
    avg = caching.cached(addon_aggregates, 'task.bayes.avg', 60 * 60 * 60)
    # Rating can be NULL in the DB, so don't update it if it's not there.
    if avg['rating'] is None:
        return
    mc = avg['reviews'] * avg['rating']
    for addon in Addon.objects.no_cache().filter(id__in=addons):
        if addon.average_rating is None:
            # Ignoring addons with no average rating.
            continue

        # Update the addon bayesian_rating atomically using F objects (unless
        # it has no reviews, in which case directly set it to 0).
        qs = Addon.objects.filter(id=addon.id)
        if addon.total_reviews:
            num = mc + F('total_reviews') * F('average_rating')
            denom = avg['reviews'] + F('total_reviews')
            qs.update(bayesian_rating=num / denom)
        else:
            qs.update(bayesian_rating=0)


@task
@write
def addon_grouped_rating(*addons, **kw):
    """Roll up add-on ratings for the bar chart."""
    # We stick this all in memcached since it's not critical.
    log.info('[%s@%s] Updating addon grouped ratings.' %
             (len(addons), addon_grouped_rating.rate_limit))
    for addon in addons:
        GroupedRating.set(addon, using='default')
