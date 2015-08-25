import logging

from django.db.models import Count, Avg, F

import caching.base as caching

from addons.models import Addon
from amo.celery import task
from .models import Review, GroupedRating

log = logging.getLogger('z.task')


@task(rate_limit='50/m')
def update_denorm(*pairs, **kw):
    """
    Takes a bunch of (addon, user) pairs and sets the denormalized fields for
    all reviews matching that pair.
    """
    log.info('[%s@%s] Updating review denorms.' %
             (len(pairs), update_denorm.rate_limit))
    using = kw.get('using')
    for addon, user in pairs:
        reviews = list(Review.objects.valid().no_cache().using(using)
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
def addon_review_aggregates(addons, **kw):
    if isinstance(addons, (int, long)):  # Got passed a single addon id.
        addons = [addons]
    log.info('[%s@%s] Updating total reviews and average ratings.' %
             (len(addons), addon_review_aggregates.rate_limit))
    using = kw.get('using')
    addon_objs = list(Addon.objects.filter(pk__in=addons))
    # The following returns something like
    # [{'rating': 2.0, 'addon': 7L, 'count': 5},
    #  {'rating': 3.75, 'addon': 6L, 'count': 8}, ...]
    qs = (Review.objects.valid().no_cache().using(using)
          .values('addon')  # Group by addon id.
          .annotate(rating=Avg('rating'), count=Count('addon')))  # Aggregates.
    stats = dict((x['addon'], (x['rating'], x['count'])) for x in qs)
    for addon in addon_objs:
        rating, reviews = stats.get(addon.id, [0, 0])
        addon.update(total_reviews=reviews, average_rating=rating)

    # Delay bayesian calculations to avoid slave lag.
    addon_bayesian_rating.apply_async(args=addons, countdown=5)
    addon_grouped_rating.apply_async(args=addons, kwargs={'using': using})


@task
def addon_bayesian_rating(*addons, **kw):
    def addon_aggregates():
        return Addon.objects.aggregate(rating=Avg('average_rating'),
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

        q = Addon.objects.filter(id=addon.id)
        if addon.total_reviews:
            num = mc + F('total_reviews') * F('average_rating')
            denom = avg['reviews'] + F('total_reviews')
            q.update(bayesian_rating=num / denom)
        else:
            q.update(bayesian_rating=0)


@task
def addon_grouped_rating(*addons, **kw):
    """Roll up add-on ratings for the bar chart."""
    # We stick this all in memcached since it's not critical.
    log.info('[%s@%s] Updating addon grouped ratings.' %
             (len(addons), addon_grouped_rating.rate_limit))
    using = kw.get('using')
    for addon in addons:
        GroupedRating.set(addon, using=using)
