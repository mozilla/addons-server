# -*- coding: utf-8 -*-
import mock
import test_utils
from nose.tools import eq_

from reviews import feeds


class FeedTest(test_utils.TestCase):
    # Rub some unicode all over the reviews feed.

    def setUp(self):
        self.feed = feeds.ReviewsRss()
        self.wut = u'Ελληνικά'

        self.addon = mock.Mock()
        self.addon.name = self.wut

        self.user = mock.Mock()
        self.user.nickname = None
        self.user.firstname = self.wut
        self.user.lastname = self.wut

        self.review = mock.Mock()
        self.review.title = self.wut
        self.review.rating = 4
        self.review.user = self.user

    def test_title(self):
        eq_(self.feed.title(self.addon),
            'Reviews for %s' % self.wut)

    def test_item_title(self):
        eq_(self.feed.item_title(self.review),
            'Rated %s out of 5 stars : %s' % (self.review.rating, self.wut))

        self.review.rating = None
        eq_(self.feed.item_title(self.review), self.wut)

    def test_item_author_name(self):
        eq_(self.feed.item_author_name(self.review),
            '%s %s' % (self.wut, self.wut))

        self.user.nickname = self.wut
        eq_(self.feed.item_author_name(self.review), self.wut)
