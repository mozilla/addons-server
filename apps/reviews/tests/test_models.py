from django.utils import translation


import amo.tests
from addons.models import Addon
from reviews import tasks
from reviews.models import check_spam, GroupedRating, Review, ReviewFlag, Spam
from users.models import UserProfile


class TestReviewModel(amo.tests.TestCase):
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
        assert Review.unfiltered.count() == 2

        Review.objects.filter(id=2).delete()
        assert Review.objects.count() == 0
        assert Review.unfiltered.count() == 2

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


class TestGroupedRating(amo.tests.TestCase):
    fixtures = ['reviews/dev-reply']
    grouped_ratings = [(1, 0), (2, 0), (3, 0), (4, 1), (5, 0)]

    def test_get_none(self):
        assert GroupedRating.get(3, update_none=False) is None

    def test_set(self):
        assert GroupedRating.get(1865, update_none=False) is None
        GroupedRating.set(1865)
        assert GroupedRating.get(1865, update_none=False) == self.grouped_ratings

    def test_cron(self):
        assert GroupedRating.get(1865, update_none=False) is None
        tasks.addon_grouped_rating(1865)
        assert GroupedRating.get(1865, update_none=False) == self.grouped_ratings

    def test_update_none(self):
        assert GroupedRating.get(1865, update_none=False) is None
        assert GroupedRating.get(1865, update_none=True) == self.grouped_ratings


class TestSpamTest(amo.tests.TestCase):
    fixtures = ['reviews/test_models']

    def test_create_not_there(self):
        Review.objects.all().delete()
        assert Review.objects.count() == 0
        check_spam(1)

    def test_add(self):
        assert Spam().add(Review.objects.all()[0], 'numbers')


class TestRefreshTest(amo.tests.ESTestCase):
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
