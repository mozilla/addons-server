import mock

from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.reviews.models import Review
from olympia.reviews.tasks import addon_review_aggregates


class TestAddonReviewAggregates(TestCase):
    @classmethod
    # Prevent <Review>.refresh() from being fired when setting up test data,
    # since it'd call addon_review_aggregates too early.
    @mock.patch.object(Review, 'refresh', lambda x, update_denorm=False: None)
    def test_total_reviews(self):
        addon = addon_factory()
        addon2 = addon_factory()

        # Create a few reviews with various ratings.
        review = Review.objects.create(
            addon=addon, rating=3, user=user_factory())
        Review.objects.create(addon=addon, rating=3, user=user_factory())
        Review.objects.create(addon=addon, rating=2, user=user_factory())
        Review.objects.create(addon=addon, rating=1, user=user_factory())

        # On another addon as well.
        Review.objects.create(addon=addon2, rating=1, user=user_factory())
        Review.objects.create(addon=addon2, rating=1, user=user_factory())

        # addon_review_aggregates should ignore replies, so let's add one.
        Review.objects.create(
            addon=addon, rating=5, user=user_factory(), reply_to=review)

        # Make sure total_reviews hasn't been updated yet.
        addon.reload()
        addon2.reload()
        assert addon.total_reviews == 0
        assert addon2.total_reviews == 0

        # Trigger the task and test results.
        addon_review_aggregates([addon.pk, addon2.pk])
        addon.reload()
        addon2.reload()
        assert addon.total_reviews == 4
        assert addon2.total_reviews == 2

        # Trigger the task with a single add-on.
        Review.objects.create(addon=addon2, rating=5, user=user_factory())
        addon2.reload()
        assert addon2.total_reviews == 2

        addon_review_aggregates(addon2.pk)
        addon2.reload()
        assert addon2.total_reviews == 3
