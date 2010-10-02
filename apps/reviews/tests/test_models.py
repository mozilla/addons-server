from django.core.cache import cache
from django.utils import translation

import test_utils
from nose.tools import eq_

from reviews import tasks
from reviews.models import Review, GroupedRating


class TestReviewModel(test_utils.TestCase):
    fixtures = ['base/apps', 'reviews/test_models.json']

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


class TestGroupedRating(test_utils.TestCase):
    fixtures = ['base/apps', 'reviews/dev-reply.json']

    def setUp(self):
        cache.set(GroupedRating.key(1865), None)

    def test_get_none(self):
        eq_(GroupedRating.get(3), None)

    def test_set(self):
        eq_(GroupedRating.get(1865), None)
        GroupedRating.set(1865)
        eq_(GroupedRating.get(1865), [(1, 0), (2, 0), (3, 0), (4, 1), (5, 0)])

    def test_cron(self):
        eq_(GroupedRating.get(1865), None)
        tasks.addon_grouped_rating(1865)
        eq_(GroupedRating.get(1865), [(1, 0), (2, 0), (3, 0), (4, 1), (5, 0)])
