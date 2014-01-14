from nose.tools import ok_

from django.core.exceptions import ValidationError

import amo.tests
from mkt.feed.models import FeedApp
from mkt.webapps.models import Webapp

from .test_views import FeedAppMixin


class TestFeedApp(FeedAppMixin, amo.tests.TestCase):

    def setUp(self):
        super(TestFeedApp, self).setUp()
        self.feedapp_data.update(**self.pullquote_data)
        self.feedapp_data['app'] = (
            Webapp.objects.get(pk=self.feedapp_data['app']))

    def test_create(self):
        feedapp = FeedApp(**self.feedapp_data)
        ok_(isinstance(feedapp, FeedApp))
        feedapp.clean_fields()  # Tests validators on fields.
        feedapp.clean()  # Test model validation.
        feedapp.save()  # Tests required fields.

    def test_missing_pullquote_rating(self):
        del self.feedapp_data['pullquote_rating']
        self.test_create()

    def test_missing_pullquote_text(self):
        del self.feedapp_data['pullquote_text']
        with self.assertRaises(ValidationError):
            self.test_create()

    def test_pullquote_rating_fractional(self):
        """
        This passes because PositiveSmallIntegerField will coerce the float into
        an int, which effectively returns math.floor(value).
        """
        self.feedapp_data['pullquote_rating'] = 4.5
        self.test_create()

    def test_bad_pullquote_rating_low(self):
        self.feedapp_data['pullquote_rating'] = -1
        with self.assertRaises(ValidationError):
            self.test_create()

    def test_bad_pullquote_rating_high(self):
        self.feedapp_data['pullquote_rating'] = 6
        with self.assertRaises(ValidationError):
            self.test_create()
