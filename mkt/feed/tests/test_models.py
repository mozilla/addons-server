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
        if not isinstance(self.feedapp_data['app'], Webapp):
            self.feedapp_data['app'] = (
                Webapp.objects.get(pk=self.feedapp_data['app']))

    def test_create(self, expected_is_valid=True):
        feedapp = FeedApp(**self.feedapp_data)
        ok_(isinstance(feedapp, FeedApp))
        feedapp.clean()
        feedapp.save()

    def test_create_missing_pullquote_rating(self):
        del self.feedapp_data['pullquote_rating']
        self.test_create()

    def test_create_missing_pullquote_text(self):
        del self.feedapp_data['pullquote_text']
        with self.assertRaises(ValidationError):
            self.test_create(expected_is_valid=False)

    def test_create_bad_pullquote_rating_fractional(self):
        self.feedapp_data['pullquote_rating'] = 4.5
        with self.assertRaises(ValidationError):
            self.test_create(expected_is_valid=False)

    def test_create_bad_pullquote_rating_low(self):
        self.feedapp_data['pullquote_rating'] = -1
        with self.assertRaises(ValidationError):
            self.test_create(expected_is_valid=False)

    def test_create_bad_pullquote_rating_range(self):
        self.feedapp_data['pullquote_rating'] = 6
        with self.assertRaises(ValidationError):
            self.test_create(expected_is_valid=False)
