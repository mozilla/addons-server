# -*- coding: utf-8 -*-
import mock

from olympia.amo.tests import TestCase
from olympia.ratings import feeds
from olympia.translations.models import Translation


class FeedTest(TestCase):
    # Rub some unicode all over the reviews feed.

    def setUp(self):
        super(FeedTest, self).setUp()
        self.feed = feeds.RatingsRss()
        self.u = u'Ελληνικά'
        self.wut = Translation(localized_string=self.u, locale='el')

        self.addon = mock.Mock()
        self.addon.name = self.wut

        self.user = mock.Mock()
        self.user.name = self.u

        self.rating = mock.Mock()
        self.rating.body = self.wut
        self.rating.rating = 4
        self.rating.user = self.user

    def test_title(self):
        assert self.feed.title(self.addon) == (
            u'Reviews for %s' % self.u)

    def test_item_title(self):
        assert self.feed.item_title(self.rating) == (
            'Rated %s out of 5 stars' % self.rating.rating)

        self.rating.rating = None
        assert self.feed.item_title(self.rating) == ''

    def test_item_author_name(self):
        assert self.feed.item_author_name(self.rating) == self.u

        self.user.username = self.u
        assert self.feed.item_author_name(self.rating) == self.u
