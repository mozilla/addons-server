# -*- coding: utf-8 -*-
from django.conf import settings

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

from amo.urlresolvers import reverse
import amo.tests
from reviews import feeds
from translations.models import Translation
from webapps.models import Webapp


class FeedTest(amo.tests.TestCase):
    # Rub some unicode all over the reviews feed.

    def setUp(self):
        self.feed = feeds.ReviewsRss()
        self.u = u'Ελληνικά'
        self.wut = Translation(localized_string=self.u, locale='el')

        self.addon = mock.Mock()
        self.addon.name = self.wut

        self.user = mock.Mock()
        self.user.username = None
        self.user.firstname = self.u
        self.user.lastname = self.u

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
        eq_(self.feed.item_author_name(self.review),
            '%s %s' % (self.u, self.u))

        self.user.username = self.u
        eq_(self.feed.item_author_name(self.review), self.u)


class TestAppsFeed(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.app = Webapp.objects.get(id=337141)
        self.url = reverse('apps.reviews.list.rss', args=[self.app.app_slug])

    def test_get(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        return r

    def get_pq(self):
        # PyQuery doesn't know RDF, and files.utils.RDF is overkill.
        return pq(self.test_get().content.replace('atom:', 'atom_'))

    def test_title(self):
        eq_(self.get_pq()('title').text(), 'Reviews for Something Something!')

    @mock.patch.object(settings, 'SITE_URL', 'http://test.com')
    def test_link(self):
        url = self.get_pq()('atom_link').attr('href')
        assert url.endswith(self.url), (
            'Unexpected URL for <atom:link>: %r' % url)

    @mock.patch.object(settings, 'APP_PREVIEW', True)
    def test_site_link(self):
        url = self.get_pq()('link').text()
        assert url.endswith(reverse('apps.home')), (
            'Unexpected URL for <link>: %r' % url)
