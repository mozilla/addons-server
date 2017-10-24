# -*- coding: utf-8 -*-
import mock

from olympia.amo.tests import TestCase
from olympia.ratings import feeds
from olympia.translations.models import Translation


class FeedTest(TestCase):
    # Rub some unicode all over the reviews feed.

    def setUp(self):
        super(FeedTest, self).setUp()
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
        assert self.feed.title(self.addon) == (
            u'Reviews for %s' % self.u)

    def test_item_title(self):
        assert self.feed.item_title(self.review) == (
            'Rated %s out of 5 stars : %s' % (self.review.rating, self.u))

        self.review.rating = None
        assert self.feed.item_title(self.review) == self.u

    def test_item_author_name(self):
        assert self.feed.item_author_name(self.review) == self.u

        self.user.username = self.u
        assert self.feed.item_author_name(self.review) == self.u
