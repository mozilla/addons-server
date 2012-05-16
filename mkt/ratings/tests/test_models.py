from django.utils import translation

from nose.tools import eq_
from test_utils import trans_eq

import amo.tests

from mkt.ratings.models import Rating
from mkt.webapps.models import Webapp


class TestRating(amo.tests.TestCase):
    fixtures = ['base/apps', 'ratings/rating']

    def test_creation(self):
        app = Webapp.objects.all()[0]
        body = 'ball so hard this ish cray'
        r = Rating.objects.create(addon=app, body=body, score=1, user_id=1)
        eq_(r.get_url_path(), app.get_ratings_url('detail', args=[r.id]))
        eq_(unicode(r.body), body)
        eq_(r.score, 1)

    def test_translations(self):
        translation.activate('en-US')

        # There's en-US and de translations.  We should get en-US.
        r1 = Rating.objects.get(id=1)
        trans_eq(r1.body, 'r1 body en', 'en-US')

        # There's only a de translation, so we get that.
        r2 = Rating.objects.get(id=2)
        trans_eq(r2.body, 'r2 body de', 'de')

        translation.activate('de')

        # en and de exist, we get de.
        r1 = Rating.objects.get(id=1)
        trans_eq(r1.body, 'r1 body de', 'de')

        # There's only a de translation, so we get that.
        r2 = Rating.objects.get(id=2)
        trans_eq(r2.body, 'r2 body de', 'de')
