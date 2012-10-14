from django.utils import translation

from nose.tools import eq_
import test_utils

import amo.tests
from addons.models import Addon
from reviews import tasks
from reviews.models import check_spam, Review, GroupedRating, Spam
from users.models import UserProfile


class TestReviewModel(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/platforms', 'reviews/test_models']

    def test_translations(self):
        translation.activate('en-US')

        # There's en-US and de translations.  We should get en-US.
        r1 = Review.objects.get(id=1)
        test_utils.trans_eq(r1.title, 'r1 title en', 'en-US')

        # There's only a de translation, so we get that.
        r2 = Review.objects.get(id=2)
        test_utils.trans_eq(r2.title, 'r2 title de', 'de')

        translation.activate('de')

        # en and de exist, we get de.
        r1 = Review.objects.get(id=1)
        test_utils.trans_eq(r1.title, 'r1 title de', 'de')

        # There's only a de translation, so we get that.
        r2 = Review.objects.get(id=2)
        test_utils.trans_eq(r2.title, 'r2 title de', 'de')


class TestGroupedRating(amo.tests.TestCase):
    fixtures = ['base/apps', 'reviews/dev-reply']
    grouped_ratings = [(1, 0), (2, 0), (3, 0), (4, 1), (5, 0)]

    def test_get_none(self):
        eq_(GroupedRating.get(3, update_none=False), None)

    def test_set(self):
        eq_(GroupedRating.get(1865, update_none=False), None)
        GroupedRating.set(1865)
        eq_(GroupedRating.get(1865, update_none=False), self.grouped_ratings)

    def test_cron(self):
        eq_(GroupedRating.get(1865, update_none=False), None)
        tasks.addon_grouped_rating(1865)
        eq_(GroupedRating.get(1865, update_none=False), self.grouped_ratings)

    def test_update_none(self):
        eq_(GroupedRating.get(1865, update_none=False), None)
        eq_(GroupedRating.get(1865, update_none=True), self.grouped_ratings)


class TestSpamTest(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/platforms', 'reviews/test_models']

    def test_create_not_there(self):
        Review.objects.all().delete()
        eq_(Review.objects.count(), 0)
        check_spam(1)

    def test_add(self):
        assert Spam().add(Review.objects.all()[0], 'numbers')


class TestRefreshTest(amo.tests.ESTestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)
        self.user = UserProfile.objects.all()[0]
        self.refresh()

        eq_(self.get_bayesian_rating(), 0.0)

    def get_bayesian_rating(self):
        q = Addon.search().filter(id=self.addon.id)
        return list(q.values_dict('bayesian_rating'))[0]['bayesian_rating']

    def test_created(self):
        eq_(self.get_bayesian_rating(), 0.0)
        Review.objects.create(addon=self.addon, user=self.user, rating=4)
        self.refresh()
        eq_(self.get_bayesian_rating(), 4.0)

    def test_edited(self):
        self.test_created()

        r = self.addon.reviews.all()[0]
        r.rating = 1
        r.save()
        self.refresh()

        eq_(self.get_bayesian_rating(), 2.5)

    def test_deleted(self):
        self.test_created()

        r = self.addon.reviews.all()[0]
        r.delete()
        self.refresh()

        eq_(self.get_bayesian_rating(), 0.0)
