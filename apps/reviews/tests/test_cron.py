import mock
from nose.tools import eq_
import test_utils

from reviews import cron, tasks
from reviews.models import Review


class TestDenormalization(test_utils.TestCase):
    fixtures = ['reviews/three-reviews']

    def setUp(self):
        Review.objects.update(is_latest=True, previous_count=0)

    def _check(self):
        reviews = list(Review.objects.order_by('created'))
        for idx, review in enumerate(reviews[:-1]):
            eq_(review.is_latest, False)
            eq_(review.previous_count, idx)
        r = reviews[-1]
        r.is_latest = True
        r.previous_count = len(reviews) - 1

    @mock.patch('reviews.tasks.update_denorm.apply_async')
    def test_denorms(self, async):
        cron.reviews_denorm()
        kwargs = async.call_args[1]
        tasks.update_denorm(*kwargs['args'])
        self._check()

    def test_denorm_on_save(self):
        addon, user = Review.objects.values_list('addon', 'user')[0]
        Review.objects.create(addon_id=addon, user_id=user)
        self._check()

    def test_denorm_on_delete(self):
        r = Review.objects.order_by('created')[1]
        r.delete()
        self._check()
