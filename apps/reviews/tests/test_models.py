from django import test
from django.utils import translation

from test_utils import trans_eq

from reviews.models import Review


class TestReviewModel(test.TestCase):
    fixtures = ['reviews/test_models.json']


    def test_translations(self):
        translation.activate('en-US')

        # There's en-US and de translations.  We should get en-US.
        r1 = Review.objects.get(id=1)
        trans_eq(r1.title, 'r1 title en', 'en-US')

        # There's only a de translation, so we get that.
        r2 = Review.objects.get(id=2)
        trans_eq(r2.title, 'r2 title de', 'de')

        translation.activate('de')

        # en and de exist, we get de.
        r1 = Review.objects.get(id=1)
        trans_eq(r1.title, 'r1 title de', 'de')

        # There's only a de translation, so we get that.
        r2 = Review.objects.get(id=2)
        trans_eq(r2.title, 'r2 title de', 'de')
