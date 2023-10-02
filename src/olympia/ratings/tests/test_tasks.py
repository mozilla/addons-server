from unittest import mock

from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.ratings.models import Rating, RatingAggregate
from olympia.ratings.tasks import addon_rating_aggregates


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
