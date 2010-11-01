import mock
from nose.tools import eq_, assert_almost_equal
import test_utils

from addons.models import Addon
from reviews import cron, tasks
from reviews.models import Review


class TestDenormalization(test_utils.TestCase):
    fixtures = ['reviews/three-reviews']

    def setUp(self):
        Review.objects.update(is_latest=True, previous_count=0)
        Addon.objects.update(total_reviews=0, average_rating=0,
                             bayesian_rating=0)

    def _check(self):
        reviews = list(Review.objects.order_by('created'))
        for idx, review in enumerate(reviews[:-1]):
            eq_(review.is_latest, False)
            eq_(review.previous_count, idx)
        r = reviews[-1]
        r.is_latest = True
        r.previous_count = len(reviews) - 1

    def _check_addon(self):
        addon = Addon.objects.get(id=72)
        eq_(addon.total_reviews, 3)
        assert_almost_equal(addon.average_rating, 2.3333, places=2)
        assert_almost_equal(addon.bayesian_rating, 2.2499, places=2)

    def test_denorms(self):
        cron.reviews_denorm()
        self._check()

    def test_denorm_on_save(self):
        addon, user = Review.objects.values_list('addon', 'user')[0]
        Review.objects.create(addon_id=addon, user_id=user, rating=3)
        self._check()

    def test_denorm_on_delete(self):
        r = Review.objects.order_by('created')[1]
        r.delete()
        self._check()

    def test_addon_review_aggregates(self):
        tasks.addon_review_aggregates(72, 3)
        self._check_addon()

    def test_cron_review_aggregate(self):
        cron.addon_reviews_ratings()
        self._check_addon()

    def test_deleted_reviews(self):
        "If all reviews are deleted, reviews and ratings should be cleared."
        tasks.addon_review_aggregates(72, 3)
        self._check_addon()
        Review.objects.all().delete()
        addon = Addon.objects.get(id=72)
        eq_(addon.total_reviews, 0)
        eq_(addon.average_rating, 0)
        eq_(addon.bayesian_rating, 0)
