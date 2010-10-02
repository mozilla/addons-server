# -*- coding: utf8 -*-
"""Check all our redirects from remora to zamboni."""
from nose.tools import eq_
import test_utils

import amo
from addons.models import Category
from applications.models import Application


class TestRedirects(test_utils.TestCase):
    fixtures = ['base/apps', 'reviews/test_models', 'base/global-stats']

    def test_persona_category(self):
        """`/personas/film and tv` should go to /personas/film-and-tv"""
        r = self.client.get('personas/film and tv', follow=True)
        assert r.redirect_chain[-1][0].endswith(
                '/en-US/firefox/personas/film-and-tv')

    def test_top_tags(self):
        """`/top-tags/?` should 301 to `/tags/top`."""
        response = self.client.get(u'top-tags/', follow=True)
        self.assertRedirects(response, '/en-US/firefox/tags/top',
                             status_code=301)

    def test_persona(self):
        """`/persona/\d+` should go to `/addon/\d+`."""
        r = self.client.get(u'persona/4', follow=True)
        assert r.redirect_chain[-1][0].endswith('/en-US/firefox/addon/4/')

    def test_contribute_installed(self):
        """`/addon/\d+/about` should go to
           `/addon/\d+/contribute/installed`."""
        r = self.client.get(u'addon/5326/about', follow=True)
        redirect = r.redirect_chain[-1][0]
        assert redirect.endswith(
                        '/en-US/firefox/addon/5326/contribute/installed/')

    def test_contribute(self):
        """`/addons/contribute/$id` should go to `/addon/$id/contribute`."""
        response = self.client.get(u'addon/5326/contribute', follow=True)
        redirect = response.redirect_chain[-1][0]
        assert redirect.endswith('/en-US/firefox/addon/5326/contribute/')

    def test_utf8(self):
        """Without proper unicode handling this will fail."""
        response = self.client.get(u'/api/1.5/search/ツールバー',
                                   follow=True)
        # Sphinx will be off so let's just test that it redirects.
        eq_(response.redirect_chain[0][1], 301)

    def test_parameters(self):
        """Bug 554976. Make sure when we redirect, we preserve our query
        strings."""
        url = u'/users/login?to=/en-US/firefox/users/edit'
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, '/en-US/firefox' + url, status_code=301)

    def test_reviews(self):
        response = self.client.get('/reviews/display/4', follow=True)
        self.assertRedirects(response, '/en-US/firefox/addon/4/reviews/',
                             status_code=301)

    def test_browse(self):
        response = self.client.get('/browse/type:3', follow=True)
        self.assertRedirects(response, '/en-US/firefox/language-tools/',
                             status_code=301)

        response = self.client.get('/browse/type:2', follow=True)
        self.assertRedirects(response, '/en-US/firefox/themes/',
                             status_code=301)

        # Drop the category.
        response = self.client.get('/browse/type:2/cat:all', follow=True)
        self.assertRedirects(response, '/en-US/firefox/themes/',
                             status_code=301)

    def test_accept_language(self):
        """
        Given an Accept Language header, do the right thing.  See bug 439568
        for juicy details.
        """

        # User wants de.  We send de
        response = self.client.get('/', follow=True, HTTP_ACCEPT_LANGUAGE='de')
        self.assertRedirects(response, '/de/firefox/', status_code=301)

        # User wants en-US, de.  We send en-US
        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='en-us, de')
        self.assertRedirects(response, '/en-US/firefox/', status_code=301)

        # User wants fr, en.  We send fr
        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='fr, en')
        self.assertRedirects(response, '/fr/firefox/', status_code=301)

        # User wants pt-XX, xx, yy.  We send pt-BR
        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt-XX, xx, yy')
        self.assertRedirects(response, '/pt-BR/firefox/', status_code=301)

        # User wants pt.  We send pt-BR
        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt')
        self.assertRedirects(response, '/pt-BR/firefox/', status_code=301)

        # User wants pt, de.  We send de
        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt, de')
        self.assertRedirects(response, '/de/firefox/', status_code=301)

        # User wants pt-XX, xx, de.  We send de
        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt-XX, xx, de')
        self.assertRedirects(response, '/de/firefox/', status_code=301)

        # User wants de-XX, xx, en-XX.  We send de
        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt-XX, xx, de')
        self.assertRedirects(response, '/de/firefox/', status_code=301)

        # User wants xx, yy, zz.  We send en-US
        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='xx, yy, zz')
        self.assertRedirects(response, '/en-US/firefox/', status_code=301)

        # User wants some,thing-very;very,,,broken!\'jj.  We send en-US
        response = self.client.get('/', follow=True,
                   HTTP_ACCEPT_LANGUAGE='some,thing-very;very,,,broken!\'jj')
        self.assertRedirects(response, '/en-US/firefox/', status_code=301)

        # User wants en-US;q=0.5, de.  We send de
        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='en-us;q=0.5, de')
        self.assertRedirects(response, '/de/firefox/', status_code=301)

    def test_users(self):
        response = self.client.get('/users/info/1', follow=True)
        self.assertRedirects(response, '/en-US/firefox/user/1/',
                             status_code=301)

    def test_extension_sorting(self):
        r = self.client.get('/browse/type:1?sort=updated', follow=True)
        self.assertRedirects(r, '/en-US/firefox/extensions/?sort=updated',
                             status_code=301)
        r = self.client.get('/browse/type:1?sort=name', follow=True)
        self.assertRedirects(r, '/en-US/firefox/extensions/?sort=name',
                             status_code=301)
        r = self.client.get('/browse/type:1?sort=newest', follow=True)
        self.assertRedirects(r, '/en-US/firefox/extensions/?sort=created',
                             status_code=301)
        r = self.client.get('/browse/type:1?sort=weeklydownloads', follow=True)
        self.assertRedirects(r, '/en-US/firefox/extensions/?sort=popular',
                             status_code=301)
        r = self.client.get('/browse/type:1?sort=averagerating', follow=True)
        self.assertRedirects(r, '/en-US/firefox/extensions/?sort=rating',
                             status_code=301)
        # If we don't recognize the sort, they get nothing.
        r = self.client.get('/browse/type:1?sort=xxx', follow=True)
        self.assertRedirects(r, '/en-US/firefox/extensions/',
                             status_code=301)

        a = Application.objects.create()
        Category.objects.create(pk=12, slug='woo', type=amo.ADDON_EXTENSION,
                                application=a, count=1, weight=0)
        r = self.client.get('/browse/type:1/cat:12?sort=averagerating',
                            follow=True)
        url, code = r.redirect_chain[-1]
        eq_(code, 301)
        assert url.endswith('/en-US/firefox/extensions/woo/?sort=rating')

    def test_addons_versions(self):
        r = self.client.get('/addons/versions/4', follow=True)
        self.assertRedirects(r, '/en-US/firefox/addon/4/versions/',
                             status_code=301)

    def test_addons_versions_rss(self):
        r = self.client.get('/addons/versions/4/format:rss', follow=True)
        self.assertRedirects(r, '/en-US/firefox/addon/4/versions/format:rss',
                             status_code=301)

    def test_addons_reviews_rss(self):
        r = self.client.get('/addons/reviews/4/format:rss', follow=True)
        self.assertRedirects(r, '/en-US/firefox/addon/4/reviews/format:rss',
                             status_code=301)
