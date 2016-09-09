import mock

from django.utils import translation

from olympia import amo
from olympia.amo.tests import addon_factory, TestCase, ESTestCase, user_factory
from olympia.addons.models import Addon
from olympia.reviews import tasks
from olympia.reviews.models import (
    check_spam, GroupedRating, Review, ReviewFlag, Spam)
from olympia.users.models import UserProfile


class TestReviewModel(TestCase):
    fixtures = ['reviews/test_models']

    def test_translations(self):
        translation.activate('en-US')

        # There's en-US and de translations.  We should get en-US.
        r1 = Review.objects.get(id=1)
        self.trans_eq(r1.title, 'r1 title en', 'en-US')

        # There's only a de translation, so we get that.
        r2 = Review.objects.get(id=2)
        self.trans_eq(r2.title, 'r2 title de', 'de')

        translation.activate('de')

        # en and de exist, we get de.
        r1 = Review.objects.get(id=1)
        self.trans_eq(r1.title, 'r1 title de', 'de')

        # There's only a de translation, so we get that.
        r2 = Review.objects.get(id=2)
        self.trans_eq(r2.title, 'r2 title de', 'de')

    def test_soft_delete(self):
        assert Review.objects.count() == 2
        assert Review.unfiltered.count() == 2

        Review.objects.get(id=1).delete()

        assert Review.objects.count() == 1
        assert Review.without_replies.count() == 1
        assert Review.unfiltered.count() == 2

    def test_soft_delete_replies_are_hidden(self):
        review = Review.objects.get(pk=1)
        Review.objects.create(
            addon=review.addon, reply_to=review,
            user=UserProfile.objects.all()[0])
        assert Review.objects.count() == 3
        assert Review.unfiltered.count() == 3
        assert Review.without_replies.count() == 2

        Review.objects.get(id=1).delete()

        # objects should only have 1 object, because we deleted the parent
        # review of the one we just created, so it should not be returned.
        assert Review.objects.count() == 1

        # without_replies should also only have 1 object, because, because it
        # does not include replies anyway.
        assert Review.without_replies.count() == 1

        # Unfiltered should have them all still.
        assert Review.unfiltered.count() == 3

    def test_filter_for_many_to_many(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        review = Review.objects.get(id=1)
        addon = review.addon
        assert review in addon._reviews.all()

        # Delete the review: it shouldn't be listed anymore.
        review.update(deleted=True)
        addon = Addon.objects.get(pk=addon.pk)
        assert review not in addon._reviews.all()

    def test_no_filter_for_relations(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        review = Review.objects.get(id=1)
        flag = ReviewFlag.objects.create(review=review,
                                         flag='review_flag_reason_spam')
        assert flag.review == review

        # Delete the review: reviewflag.review should still work.
        review.update(deleted=True)
        flag = ReviewFlag.objects.get(pk=flag.pk)
        assert flag.review == review


class TestGroupedRating(TestCase):
    @classmethod
    # Prevent <Review>.refresh() from being fired when setting up test data,
    # since it'd affect the results of our tests by calculating GroupedRating
    # results early (and storing result in cache) or changing is_latest boolean
    # on reviews.
    @mock.patch.object(Review, 'refresh', lambda x, update_denorm=False: None)
    def setUpTestData(cls):
        cls.addon = addon_factory()
        user = user_factory()

        # Create a few reviews with various ratings.
        review = Review.objects.create(addon=cls.addon, rating=3, user=user)
        Review.objects.create(addon=cls.addon, rating=3, user=user_factory())
        Review.objects.create(addon=cls.addon, rating=2, user=user_factory())
        Review.objects.create(addon=cls.addon, rating=1, user=user_factory())
        Review.objects.create(addon=cls.addon, rating=1, user=user_factory())
        Review.objects.create(addon=cls.addon, rating=1, user=user_factory())

        # GroupedRating should ignore replies, so let's add one.
        Review.objects.create(
            addon=cls.addon, rating=5, user=user_factory(), reply_to=review)

        # GroupedRating should also ignore reviews that aren't the latest for
        # this user and addon, so let's add another one from the same user.
        Review.objects.create(
            addon=cls.addon, rating=4, user=user, is_latest=False)

        # There are three '1' ratings, one '2' rating, 2 'three' ratings,
        # and zero for '4' and '5' since replies and non-latest reviews do not
        # count.
        cls.expected_grouped_rating = [(1, 3), (2, 1), (3, 2), (4, 0), (5, 0)]

    def test_get_unknown_addon_id(self):
        assert GroupedRating.get(3, update_none=False) is None
        assert GroupedRating.get(3) == [(1, 0), (2, 0), (3, 0), (4, 0), (5, 0)]

    def test_set(self):
        assert GroupedRating.get(self.addon.pk, update_none=False) is None
        GroupedRating.set(self.addon.pk)
        assert GroupedRating.get(self.addon.pk, update_none=False) == (
            self.expected_grouped_rating)

    def test_cron(self):
        assert GroupedRating.get(self.addon.pk, update_none=False) is None
        tasks.addon_grouped_rating(self.addon.pk)
        assert GroupedRating.get(self.addon.pk, update_none=False) == (
            self.expected_grouped_rating)

    def test_update_none(self):
        assert GroupedRating.get(self.addon.pk, update_none=False) is None
        assert GroupedRating.get(self.addon.pk, update_none=True) == (
            self.expected_grouped_rating)


class TestSpamTest(TestCase):
    fixtures = ['reviews/test_models']

    def test_create_not_there(self):
        Review.objects.all().delete()
        assert Review.objects.count() == 0
        check_spam(1)

    def test_add(self):
        assert Spam().add(Review.objects.all()[0], 'numbers')


class TestRefreshTest(ESTestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestRefreshTest, self).setUp()
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.user = UserProfile.objects.all()[0]
        self.refresh()

        assert self.get_bayesian_rating() == 0.0

    def get_bayesian_rating(self):
        q = Addon.search().filter(id=self.addon.id)
        return list(q.values_dict('bayesian_rating'))[0]['bayesian_rating'][0]

    def test_created(self):
        assert self.get_bayesian_rating() == 0.0
        Review.objects.create(addon=self.addon, user=self.user, rating=4)
        self.refresh()
        assert self.get_bayesian_rating() == 4.0

    def test_edited(self):
        self.test_created()

        r = self.addon.reviews.all()[0]
        r.rating = 1
        r.save()
        self.refresh()

        assert self.get_bayesian_rating() == 2.5

    def test_deleted(self):
        self.test_created()

        r = self.addon.reviews.all()[0]
        r.delete()
        self.refresh()

        assert self.get_bayesian_rating() == 0.0
