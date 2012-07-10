# -*- coding: utf-8 -*-
from django.core.urlresolvers import reverse

import mock
from nose.tools import eq_

import amo
from mkt.ratings.feeds import RatingsRss
from reviews.tests.test_feeds import FeedTest
from translations.models import Translation


class RatingsFeedTest(FeedTest):

    def setUp(self):
        self.feed = RatingsRss()
        self.u = u'Ελληνικά'
        self.wut = Translation(localized_string=self.u, locale='el')

        self.addon = mock.Mock()
        self.addon.name = self.wut

        self.user = mock.Mock()
        self.user.name = self.u

        self.review = mock.Mock()
        self.review.title = self.wut
        self.review.rating = 4
        self.review.user = self.user

    def test_rss_page(self):
        app = amo.tests.app_factory()
        r = self.client.get(reverse('ratings.list.rss', args=[app.app_slug]))
        eq_(r.status_code, 200)
