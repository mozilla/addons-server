import json
import uuid
from datetime import datetime
from unittest import mock

from django.conf import settings

import pytest
import responses
import time_machine

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase, addon_factory, days_ago, user_factory
from olympia.files.models import File
from olympia.ratings.models import Rating, RatingAggregate
from olympia.ratings.tasks import (
    addon_rating_aggregates,
    flag_high_rating_addons_according_to_review_tier,
)
from olympia.reviewers.models import NeedsHumanReview, UsageTier
from olympia.versions.models import Version
from olympia.zadmin.models import set_config


class TestAddonRatingAggregates(TestCase):
    # Prevent Rating.post_save() from being fired when setting up test data,
    # since it'd call addon_rating_aggregates too early.
    @mock.patch.object(Rating, 'post_save', lambda *args, **kwargs: None)
    def test_addon_rating_aggregates(self):
        def get_grouped_counts(addon):
            aggregate = addon.ratingaggregate
            return {idx: getattr(aggregate, f'count_{idx}') for idx in range(1, 6)}

        addon = addon_factory()
        addon2 = addon_factory()

        # Add a purely unlisted add-on. It should not be considered when
        # calculating bayesian rating for the other add-ons.
        addon3 = addon_factory(total_ratings=3, average_rating=4)
        self.make_addon_unlisted(addon3)

        # Create a few ratings with various scores.
        user = user_factory()
        # Add an old rating that should not be used to calculate the average,
        # because the same user posts a new one right after that.
        old_rating = Rating.objects.create(
            addon=addon, rating=1, user=user, is_latest=False, body='old'
        )
        new_rating = Rating.objects.create(addon=addon, rating=3, user=user, body='new')
        Rating.objects.create(addon=addon, rating=3, user=user_factory(), body='foo')
        Rating.objects.create(addon=addon, rating=2, user=user_factory())
        Rating.objects.create(addon=addon, rating=1, user=user_factory())

        # On another addon as well.
        Rating.objects.create(addon=addon2, rating=1, user=user_factory())
        Rating.objects.create(addon=addon2, rating=1, user=user_factory(), body='two')

        # addon_rating_aggregates should ignore replies, so let's add one.
        Rating.objects.create(
            addon=addon, rating=5, user=user_factory(), reply_to=new_rating
        )

        # Make sure old_review is considered old, new_review considered new.
        old_rating.reload()
        new_rating.reload()
        assert old_rating.is_latest is False
        assert new_rating.is_latest is True

        # Make sure total_ratings hasn't been updated yet (because we are
        # mocking post_save()).
        addon.reload()
        addon2.reload()
        assert addon.total_ratings == 0
        assert addon2.total_ratings == 0
        assert addon.bayesian_rating == 0
        assert addon.average_rating == 0
        assert addon2.bayesian_rating == 0
        assert addon2.average_rating == 0
        assert addon.text_ratings_count == 0
        assert addon2.text_ratings_count == 0

        with self.assertRaises(RatingAggregate.DoesNotExist):
            addon.ratingaggregate  # noqa: B018
        with self.assertRaises(RatingAggregate.DoesNotExist):
            addon2.ratingaggregate  # noqa: B018

        # Trigger the task and test results.
        addon_rating_aggregates([addon.pk, addon2.pk])
        addon = addon.__class__.objects.get(id=addon.id)
        addon2 = addon2.__class__.objects.get(id=addon2.id)
        assert addon.total_ratings == 4
        assert addon2.total_ratings == 2
        assert addon.bayesian_rating == 1.9821428571428572
        assert addon.average_rating == 2.25
        assert addon2.bayesian_rating == 1.375
        assert addon2.average_rating == 1.0
        assert addon.text_ratings_count == 2
        assert addon2.text_ratings_count == 1
        assert get_grouped_counts(addon) == {1: 1, 2: 1, 3: 2, 4: 0, 5: 0}
        assert get_grouped_counts(addon2) == {1: 2, 2: 0, 3: 0, 4: 0, 5: 0}

        # Trigger the task with a single add-on.
        Rating.objects.create(addon=addon2, rating=5, user=user_factory(), body='xxx')
        addon2 = addon2.__class__.objects.get(id=addon2.id)
        assert addon2.total_ratings == 2
        assert get_grouped_counts(addon2) == {1: 2, 2: 0, 3: 0, 4: 0, 5: 0}

        addon_rating_aggregates(addon2.pk)
        addon2 = addon2.__class__.objects.get(id=addon2.id)
        assert addon2.total_ratings == 3
        assert addon2.text_ratings_count == 2
        assert addon.bayesian_rating == 1.9821428571428572
        assert addon.average_rating == 2.25
        assert addon2.bayesian_rating == 1.97915
        assert addon2.average_rating == 2.3333
        assert get_grouped_counts(addon2) == {1: 2, 2: 0, 3: 0, 4: 0, 5: 1}


def addon_factory_with_ratings(*, ratings_count, **kwargs):
    addon = addon_factory(**kwargs)
    for _x in range(0, ratings_count):
        Rating.objects.create(addon=addon, user=user_factory())
    return addon


def _high_ratings_setup(threshold_field):
    user_factory(pk=settings.TASK_USER_ID)
    # Create some usage tiers and add add-ons in them for the task to do
    # something. The ones missing a lower, upper, or rating threshold
    # don't do anything for this test.
    UsageTier.objects.create(name='Not a tier with usage values')
    UsageTier.objects.create(
        name='D tier (no lower threshold)',
        upper_adu_threshold=100,
        **{threshold_field: 200},
    )
    UsageTier.objects.create(
        name='C tier (no rating threshold)',
        lower_adu_threshold=100,
        upper_adu_threshold=200,
    )
    UsageTier.objects.create(
        name='B tier',
        lower_adu_threshold=200,
        upper_adu_threshold=250,
        **{threshold_field: 1},
    )
    UsageTier.objects.create(
        name='A tier',
        lower_adu_threshold=250,
        upper_adu_threshold=1000,
        **{threshold_field: 2},
    )
    UsageTier.objects.create(
        name='S tier (no upper threshold)',
        lower_adu_threshold=1000,
        upper_adu_threshold=None,
        **{threshold_field: 1},
    )

    not_flagged = [
        # Belongs to D tier, below threshold since it has 0 ratings/users.
        addon_factory(name='D tier empty addon', average_daily_users=0),
        # Belongs to D tier, below threshold since it has 1 rating and 0 users.
        addon_factory_with_ratings(
            name='D tier addon below threshold', average_daily_users=0, ratings_count=1
        ),
        # Belongs to C tier, which doesn't have a ratings threshold set.
        addon_factory_with_ratings(
            name='C tier addon', average_daily_users=100, ratings_count=2
        ),
        # Belongs to B tier but not an extension.
        addon_factory_with_ratings(
            name='B tier language pack',
            type=amo.ADDON_LPAPP,
            average_daily_users=200,
            ratings_count=3,
        ),
        addon_factory_with_ratings(
            name='B tier theme',
            type=amo.ADDON_STATICTHEME,
            average_daily_users=200,
            ratings_count=3,
        ),
        # Belongs to A tier but will be below the rating threshold.
        addon_factory_with_ratings(
            name='A tier below threshold',
            average_daily_users=250,
            ratings_count=2,
        ),
        # Belongs to S tier, which doesn't have an upper threshold. (like
        # notable, subject to human review anyway)
        addon_factory_with_ratings(
            name='S tier addon', average_daily_users=1000, ratings_count=10
        ),
        # Belongs to A tier but already human reviewed.
        addon_factory_with_ratings(
            name='A tier already reviewed',
            average_daily_users=250,
            version_kw={'human_review_date': datetime.now()},
            ratings_count=3,
        ),
        # Belongs to B tier but already disabled.
        addon_factory_with_ratings(
            name='B tier already disabled',
            average_daily_users=200,
            status=amo.STATUS_DISABLED,
            ratings_count=3,
        ),
    ]

    flagged = [
        addon_factory_with_ratings(
            name='D tier addon with ratings', average_daily_users=0, ratings_count=2
        ),
        addon_factory_with_ratings(
            name='B tier', average_daily_users=200, ratings_count=2
        ),
        addon_factory_with_ratings(
            name='A tier', average_daily_users=250, ratings_count=6
        ),
        NeedsHumanReview.objects.create(
            version=addon_factory_with_ratings(
                name='A tier with inactive flags',
                average_daily_users=250,
                ratings_count=6,
            ).current_version,
            is_active=False,
        ).version.addon,
        addon_factory_with_ratings(
            name='B tier with a rating a week old',
            average_daily_users=200,
            ratings_count=2,
        ),
    ]
    # Still exactly (to the second) within the window we care about.
    Rating.objects.filter(addon=flagged[-1]).update(created=days_ago(14))

    return not_flagged, flagged


@time_machine.travel('2023-06-26 11:00', tick=False)
@pytest.mark.django_db
def test_flag_high_rating_addons_according_to_review_tier():
    set_config(amo.config_keys.EXTRA_REVIEW_TARGET_PER_DAY, '1')
    not_flagged, flagged = _high_ratings_setup(
        'ratings_ratio_threshold_before_flagging'
    )
    # Belongs to B tier but already flagged for human review
    not_flagged.append(
        NeedsHumanReview.objects.create(
            version=addon_factory_with_ratings(
                name='B tier already flagged',
                average_daily_users=200,
                ratings_count=3,
            ).current_version,
            is_active=True,
        ).version.addon,
    )
    # Pretend all files were signed otherwise they would not get flagged.
    File.objects.update(is_signed=True)

    flag_high_rating_addons_according_to_review_tier()

    for addon in not_flagged:
        assert (
            addon.versions.latest('pk')
            .needshumanreview_set.filter(
                reason=NeedsHumanReview.REASONS.RATINGS_THRESHOLD, is_active=True
            )
            .count()
            == 0
        ), f'Addon {addon} should not have been flagged'

    for addon in flagged:
        version = addon.versions.latest('pk')
        assert (
            version.needshumanreview_set.filter(
                reason=NeedsHumanReview.REASONS.RATINGS_THRESHOLD, is_active=True
            ).count()
            == 1
        ), f'Addon {addon} should have been flagged'

    # We've set amo.config_keys.EXTRA_REVIEW_TARGET_PER_DAY so that there would be
    # one review per day after . Since we've frozen time on a Wednesday,
    # we should get: Friday, Monday (skipping week-end), Tuesday.
    due_dates = (
        Version.objects.filter(addon__in=flagged)
        .values_list('due_date', flat=True)
        .order_by('due_date')
    )
    assert list(due_dates) == [
        datetime(2023, 6, 29, 11, 0),
        datetime(2023, 6, 30, 11, 0),
        datetime(2023, 7, 3, 11, 0),
        datetime(2023, 7, 4, 11, 0),
        datetime(2023, 7, 5, 11, 0),
    ]


@time_machine.travel('2023-06-26 11:00', tick=False)
@pytest.mark.django_db
def test_block_high_rating_addons_according_to_review_tier():
    not_blocked, blocked = _high_ratings_setup(
        'ratings_ratio_threshold_before_blocking'
    )
    responses.add_callback(
        responses.POST,
        f'{settings.CINDER_SERVER_URL}create_decision',
        callback=lambda r: (201, {}, json.dumps({'uuid': uuid.uuid4().hex})),
    )

    flag_high_rating_addons_according_to_review_tier()

    for addon in not_blocked:
        addon.reload()
        assert not addon.block, f'Addon {addon} should not have been blocked'

    for addon in blocked:
        addon.reload()
        assert addon.status == amo.STATUS_DISABLED, (
            f'Addon {addon} should have been disabled'
        )
        assert addon.block, f'Addon {addon} should have have a block record'
        assert (
            not addon.versions(manager='unfiltered_for_relations')
            .filter(blockversion__isnull=True)
            .exists()
        ), f'Addon {addon}s versions should have been blocked'
        assert (
            ActivityLog.objects.filter(
                addonlog__addon=addon, action=amo.LOG.FORCE_DISABLE.id
            )
            .get()
            .details['reason']
            == 'Rejected and blocked due to: high rating count'
        )
