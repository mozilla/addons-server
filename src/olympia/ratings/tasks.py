from django.db.models import Avg, Count, F

import olympia.core.logger

from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import write
from olympia.lib.cache import cached

from .models import GroupedRating, Rating


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
        reviews = list(Rating.without_replies.all().no_cache()
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
def addon_rating_aggregates(addons, **kw):
    if isinstance(addons, (int, long)):  # Got passed a single addon id.
        addons = [addons]
    log.info('[%s@%s] Updating total reviews and average ratings.' %
             (len(addons), addon_rating_aggregates.rate_limit))
    addon_objs = list(Addon.objects.filter(pk__in=addons))
    # The following returns something like
    # [{'rating': 2.0, 'addon': 7L, 'count': 5},
    #  {'rating': 3.75, 'addon': 6L, 'count': 8}, ...]
    qs = (Rating.without_replies.all().no_cache()
          .filter(addon__in=addons, is_latest=True)
          .values('addon')  # Group by addon id.
          .annotate(rating=Avg('rating'), count=Count('addon'))  # Aggregates.
          .order_by())  # Reset order by so that `created` is not included.
    stats = {x['addon']: (x['rating'], x['count']) for x in qs}

    text_qs = (Rating.without_replies.all().no_cache()
               .filter(addon__in=addons, is_latest=True)
               .exclude(body=None)
               .values('addon')  # Group by addon id.
               .annotate(count=Count('addon'))
               .order_by())
    text_stats = {x['addon']: x['count'] for x in text_qs}

    for addon in addon_objs:
        rating, reviews = stats.get(addon.id, [0, 0])
        reviews_with_text = text_stats.get(addon.id, 0)
        addon.update(total_ratings=reviews, average_rating=rating,
                     text_ratings_count=reviews_with_text)

    # Delay bayesian calculations to avoid slave lag.
    addon_bayesian_rating.apply_async(args=addons, countdown=5)
    addon_grouped_rating.apply_async(args=addons)


@task
@write
def addon_bayesian_rating(*addons, **kw):
    def addon_aggregates():
        return Addon.objects.valid().aggregate(rating=Avg('average_rating'),
                                               reviews=Avg('total_ratings'))

    log.info('[%s@%s] Updating bayesian ratings.' %
             (len(addons), addon_bayesian_rating.rate_limit))

    avg = cached(addon_aggregates, 'task.bayes.avg', 60 * 60 * 60)
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
        if addon.total_ratings:
            num = mc + F('total_ratings') * F('average_rating')
            denom = avg['reviews'] + F('total_ratings')
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
