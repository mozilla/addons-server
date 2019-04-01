# -*- coding: utf-8 -*-
"""Check all our redirects from remora to zamboni."""

from olympia import amo
from olympia.addons.models import Category
from olympia.amo.tests import TestCase


class TestRedirects(TestCase):
    fixtures = ['ratings/test_models', 'addons/persona']

    def test_persona_category(self):
        """`/personas/film and tv/` should go to /themes/film-and-tv/"""
        r = self.client.get('/personas/film and tv', follow=True)
        assert r.redirect_chain[-1][0].endswith(
            '/en-US/firefox/themes/film-and-tv/')

    def test_reviews(self):
        response = self.client.get('/reviews/display/4', follow=True)
        self.assert3xx(response, '/en-US/firefox/addon/a4/reviews/',
                       status_code=302)

    def test_browse(self):
        response = self.client.get('/browse/type:3', follow=True)
        self.assert3xx(response, '/en-US/firefox/language-tools/',
                       status_code=302)

        response = self.client.get('/browse/type:2', follow=True)
        self.assert3xx(response, '/en-US/firefox/complete-themes/',
                       status_code=302)

        # Drop the category.
        response = self.client.get('/browse/type:2/cat:all', follow=True)
        self.assert3xx(response, '/en-US/firefox/complete-themes/',
                       status_code=302)

    def test_accept_language(self):
        """
        Given an Accept Language header, do the right thing.  See bug 439568
        for juicy details.
        """

        response = self.client.get('/', follow=True, HTTP_ACCEPT_LANGUAGE='de')
        self.assert3xx(response, '/de/firefox/', status_code=302)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='en-us, de')
        self.assert3xx(response, '/en-US/firefox/', status_code=302)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='fr, en')
        self.assert3xx(response, '/fr/firefox/', status_code=302)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt-XX, xx, yy')
        self.assert3xx(response, '/pt-PT/firefox/', status_code=302)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt')
        self.assert3xx(response, '/pt-PT/firefox/', status_code=302)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt, de')
        self.assert3xx(response, '/pt-PT/firefox/', status_code=302)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt-XX, xx, de')
        self.assert3xx(response, '/pt-PT/firefox/', status_code=302)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='xx, yy, zz')
        self.assert3xx(response, '/en-US/firefox/', status_code=302)

        response = self.client.get(
            '/', follow=True,
            HTTP_ACCEPT_LANGUAGE='some,thing-very;very,,,broken!\'jj')
        self.assert3xx(response, '/en-US/firefox/', status_code=302)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='en-us;q=0.5, de')
        self.assert3xx(response, '/de/firefox/', status_code=302)

    def test_extension_sorting(self):
        r = self.client.get('/browse/type:1?sort=updated', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/?sort=updated',
                       status_code=302)
        r = self.client.get('/browse/type:1?sort=name', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/?sort=name',
                       status_code=302)
        r = self.client.get('/browse/type:1?sort=newest', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/?sort=created',
                       status_code=302)
        r = self.client.get('/browse/type:1?sort=weeklydownloads', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/?sort=popular',
                       status_code=302)
        r = self.client.get('/browse/type:1?sort=averagerating', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/?sort=rating',
                       status_code=302)
        # If we don't recognize the sort, they get nothing.
        r = self.client.get('/browse/type:1?sort=xxx', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/',
                       status_code=302)

        Category.objects.create(pk=12, slug='woo', type=amo.ADDON_EXTENSION,
                                application=amo.FIREFOX.id, count=1, weight=0)
        r = self.client.get('/browse/type:1/cat:12?sort=averagerating',
                            follow=True)
        url, code = r.redirect_chain[-1]
        assert code == 301
        assert url.endswith('/en-US/firefox/extensions/woo/?sort=rating')

    def test_addons_versions(self):
        r = self.client.get('/addons/versions/4', follow=True)
        self.assert3xx(r, '/en-US/firefox/addon/a4/versions/', status_code=302)

    def test_addons_versions_rss(self):
        r = self.client.get('/addons/versions/4/format:rss', follow=True)
        self.assert3xx(r, '/en-US/firefox/addon/4/versions/format:rss',
                       status_code=302)

    def test_addons_reviews_rss(self):
        r = self.client.get('/addons/reviews/4/format:rss', follow=True)
        self.assert3xx(r, '/en-US/firefox/addon/4/reviews/format:rss',
                       status_code=302)
