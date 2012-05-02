# -*- coding: utf-8 -*-
import mock
from nose.tools import eq_

import amo.tests
from reviews import feeds
from translations.models import Translation


class FeedTest(amo.tests.TestCase):
    # Rub some unicode all over the reviews feed.

    def setUp(self):
        self.feed = feeds.ReviewsRss()
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

    def test_title(self):
        eq_(self.feed.title(self.addon),
            u'Reviews for %s' % self.u)

    def test_item_title(self):
        eq_(self.feed.item_title(self.review),
            'Rated %s out of 5 stars : %s' % (self.review.rating, self.u))

        self.review.rating = None
        eq_(self.feed.item_title(self.review), self.u)

    def test_item_author_name(self):
        eq_(self.feed.item_author_name(self.review), self.u)

        self.user.username = self.u
        eq_(self.feed.item_author_name(self.review), self.u)
