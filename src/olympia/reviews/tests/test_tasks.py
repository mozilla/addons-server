import mock

from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.reviews.models import Review
from olympia.reviews.tasks import addon_review_aggregates


class TestAddonReviewAggregates(TestCase):
    # Prevent <Review>.refresh() from being fired when setting up test data,
    # since it'd call addon_review_aggregates too early.
    @mock.patch.object(Review, 'refresh', lambda x, update_denorm=False: None)
    def test_addon_review_aggregates(self):
        addon = addon_factory()
        addon2 = addon_factory()

        # Add a purely unlisted add-on. It should not be considered when
        # calculating bayesian rating for the other add-ons.
        addon3 = addon_factory(total_reviews=3, average_rating=4)
        self.make_addon_unlisted(addon3)

        # Create a few reviews with various ratings.
        user = user_factory()
        # Add an old review that should not be used to calculate the average,
        # because the same user posts a new one right after that.
        old_review = Review.objects.create(
            addon=addon, rating=1, user=user, is_latest=False, body=u'old')
        new_review = Review.objects.create(addon=addon, rating=3, user=user,
                                           body=u'new')
        Review.objects.create(addon=addon, rating=3, user=user_factory(),
                              body=u'foo')
        Review.objects.create(addon=addon, rating=2, user=user_factory())
        Review.objects.create(addon=addon, rating=1, user=user_factory())

        # On another addon as well.
        Review.objects.create(addon=addon2, rating=1, user=user_factory())
        Review.objects.create(addon=addon2, rating=1, user=user_factory(),
                              body=u'two')

        # addon_review_aggregates should ignore replies, so let's add one.
        Review.objects.create(
            addon=addon, rating=5, user=user_factory(), reply_to=new_review)

        # Make sure old_review is considered old, new_review considered new.
        old_review.reload()
        new_review.reload()
        assert old_review.is_latest is False
        assert new_review.is_latest is True

        # Make sure total_reviews hasn't been updated yet (because we are
        # mocking Review.refresh()).
        addon.reload()
        addon2.reload()
        assert addon.total_reviews == 0
        assert addon2.total_reviews == 0
        assert addon.bayesian_rating == 0
        assert addon.average_rating == 0
        assert addon2.bayesian_rating == 0
        assert addon2.average_rating == 0
        assert addon.text_reviews == 0
        assert addon2.text_reviews == 0

        # Trigger the task and test results.
        addon_review_aggregates([addon.pk, addon2.pk])
        addon.reload()
        addon2.reload()
        assert addon.total_reviews == 4
        assert addon2.total_reviews == 2
        assert addon.bayesian_rating == 1.9821428571428572
        assert addon.average_rating == 2.25
        assert addon2.bayesian_rating == 1.375
        assert addon2.average_rating == 1.0
        assert addon.text_reviews == 2
        assert addon2.text_reviews == 1

        # Trigger the task with a single add-on.
        Review.objects.create(addon=addon2, rating=5, user=user_factory(),
                              body=u'xxx')
        addon2.reload()
        assert addon2.total_reviews == 2

        addon_review_aggregates(addon2.pk)
        addon2.reload()
        assert addon2.total_reviews == 3
        assert addon2.text_reviews == 2
        assert addon.bayesian_rating == 1.9821428571428572
        assert addon.average_rating == 2.25
        assert addon2.bayesian_rating == 1.97915
        assert addon2.average_rating == 2.3333
