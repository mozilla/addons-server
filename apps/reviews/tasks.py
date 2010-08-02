import logging

from django.db.models import Count, Avg, F

import caching.base as caching
from celeryutils import task

from addons.models import Addon
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
                       .filter(addon=addon, user=user)
                       .filter(reply_to=None).order_by('created'))
        if not reviews:
            continue

        for idx, review in enumerate(reviews):
            review.previous_count = idx
            review.is_latest = False
        reviews[-1].is_latest = True

        for review in reviews:
            review.save()


@task
def addon_review_aggregates(*addons, **kw):
    log.info('[%s@%s] Updating total reviews.' %
             (len(addons), addon_review_aggregates.rate_limit))
    using = kw.get('using')
    stats = dict(Review.objects.latest().filter(addon__in=addons)
                 .using(using).values_list('addon').annotate(Count('addon')))
    for addon in addons:
        count = stats.get(addon, 0)
        Addon.objects.filter(id=addon).update(total_reviews=count)

    log.info('[%s@%s] Updating average ratings.' %
             (len(addons), addon_review_aggregates.rate_limit))
    stats = dict(Review.objects.valid().filter(addon__in=addons)
                 .using(using).values_list('addon').annotate(Avg('rating')))
    for addon in addons:
        avg = stats.get(addon, 0)
        Addon.objects.filter(id=addon).update(average_rating=avg)

    # Delay bayesian calculations to avoid slave lag.
    addon_bayesian_rating.apply_async(args=addons, countdown=5)
    addon_grouped_rating.apply_async(args=addons, kwargs={'using': using})


@task
def addon_bayesian_rating(*addons, **kw):
    log.info('[%s@%s] Updating bayesian ratings.' %
             (len(addons), addon_bayesian_rating.rate_limit))
    f = lambda: Addon.objects.aggregate(rating=Avg('average_rating'),
                                        reviews=Avg('total_reviews'))
    avg = caching.cached(f, 'task.bayes.avg', 60 * 60 * 60)
    mc = avg['reviews'] * avg['rating']
    for addon in Addon.uncached.filter(id__in=addons):
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


@task(rate_limit='10/m')
def cron_review_aggregate(*addons, **kw):
    log.info('[%s@%s] Updating addon review aggregates.' %
             (len(addons), cron_review_aggregate.rate_limit))
    # We have this redundant task to get rate limiting for big chunks.
    addon_review_aggregates(*addons)
