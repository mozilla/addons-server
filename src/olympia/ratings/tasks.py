from collections import defaultdict

from django.core.cache import cache
from django.db.models import Avg, Count, F

import olympia.core.logger

from olympia.addons.models import Addon
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db

from .models import Rating, RatingAggregate


log = olympia.core.logger.getLogger('z.task')


@task(rate_limit='50/m')
@use_primary_db
def update_denorm(*pairs, **kw):
    """
    Takes a bunch of (addon, user) pairs and sets the denormalized fields for
    all reviews matching that pair.
    """
    log.info(f'[{len(pairs)}@{update_denorm.rate_limit}] Updating review denorms.')
    for addon, user in pairs:
        reviews = list(
            Rating.without_replies.all()
            .filter(addon=addon, user=user)
            .order_by('created')
        )
        if not reviews:
            continue

        data = {}
        for idx, review in enumerate(reviews):
            data[review.pk] = {
                'previous_count': idx,
                'is_latest': False,
            }
        data[reviews[-1].pk]['is_latest'] = True

        for review in reviews:
            # Update the review, without sending post_save as it would do it
            # again needlessly.
            review.update(_signal=False, **data[review.pk])


@task
@use_primary_db
def addon_rating_aggregates(addons, **kw):
    if isinstance(addons, int):  # Got passed a single addon id.
        addons = [addons]
    log.info(
        '[%s@%s] Updating total reviews and average ratings.'
        % (len(addons), addon_rating_aggregates.rate_limit)
    )
    addon_objs = list(Addon.objects.filter(pk__in=addons))

    text_qs = (
        Rating.without_replies.all()
        .filter(addon__in=addons, is_latest=True)
        .exclude(body=None)
        .values('addon')  # Group by addon id.
        .annotate(count=Count('addon'))
        .order_by()
    )
    text_stats = {x['addon']: x['count'] for x in text_qs}

    grouped_qs = (
        Rating.without_replies.all()
        .filter(addon__in=addons, is_latest=True)
        .values_list('addon_id', 'rating')
        .annotate(Count('rating'))
        .order_by()
    )
    grouped_counts = defaultdict(dict)
    for addon_id, rating, count in grouped_qs:
        grouped_counts[addon_id][rating] = count

    for addon in addon_objs:
        counts = grouped_counts.get(addon.id, {})
        total = sum(count for score, count in counts.items() if score)
        average = (
            round(
                sum(score * count for score, count in counts.items() if score and count)
                / total,
                4,
            )
            if total
            else 0
        )

        reviews_with_text = text_stats.get(addon.pk, 0)
        addon.update(
            total_ratings=total,
            average_rating=average,
            text_ratings_count=reviews_with_text,
        )

        # Update grouped ratings
        RatingAggregate.objects.update_or_create(
            addon=addon,
            defaults={f'count_{idx}': counts.get(idx, 0) for idx in range(1, 6)},
        )

    # Delay bayesian calculations to avoid slave lag.
    addon_bayesian_rating.apply_async(args=addons, countdown=5)


@task
@use_primary_db
def addon_bayesian_rating(*addons, **kw):
    def addon_aggregates():
        return Addon.objects.valid().aggregate(
            rating=Avg('average_rating'), reviews=Avg('total_ratings')
        )

    log.info(
        '[%s@%s] Updating bayesian ratings.'
        % (len(addons), addon_bayesian_rating.rate_limit)
    )

    avg = cache.get_or_set('task.bayes.avg', addon_aggregates, 60 * 60 * 60)
    # Rating can be NULL in the DB, so don't update it if it's not there.
    if avg['rating'] is None:
        return

    mc = avg['reviews'] * avg['rating']

    for addon in Addon.objects.filter(id__in=addons):
        if addon.average_rating is None:
            # Ignoring addons with no average rating.
            continue

        # Update the addon bayesian_rating atomically using F objects (unless
        # it has no reviews, in which case directly set it to 0).
        qs = Addon.objects.filter(pk=addon.pk)
        if addon.total_ratings:
            num = mc + F('total_ratings') * F('average_rating')
            denom = avg['reviews'] + F('total_ratings')
            qs.update(bayesian_rating=num / denom)
        else:
            qs.update(bayesian_rating=0)
