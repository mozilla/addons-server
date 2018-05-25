# -*- coding: utf-8 -*-
"""Check all our redirects from remora to zamboni."""
from django.db import connection

from olympia import amo
from olympia.addons.models import Category
from olympia.amo.tests import TestCase


class TestRedirects(TestCase):
    fixtures = ['ratings/test_models', 'addons/persona', 'base/global-stats']

    def test_persona_category(self):
        """`/personas/film and tv/` should go to /themes/film-and-tv/"""
        r = self.client.get('/personas/film and tv', follow=True)
        assert r.redirect_chain[-1][0].endswith(
            '/en-US/firefox/themes/film-and-tv/')

    def test_contribute_installed(self):
        """`/addon/\d+/about` should go to
           `/addon/\d+/contribute/installed`."""
        r = self.client.get(u'/addon/5326/about', follow=True)
        redirect = r.redirect_chain[-1][0]
        assert redirect.endswith(
            '/en-US/firefox/addon/5326/')

    def test_contribute(self):
        """`/addons/contribute/$id` should go to `/addon/$id/contribute`."""
        response = self.client.get(u'/addon/5326/contribute', follow=True)
        redirect = response.redirect_chain[-1][0]
        assert redirect.endswith('/en-US/firefox/addon/5326/')

    def test_utf8(self):
        """Without proper unicode handling this will fail."""
        response = self.client.get(u'/api/1.5/search/ツールバー',
                                   follow=True)
        # Sphinx will be off so let's just test that it redirects.
        assert response.redirect_chain[0][1] == 301

    def test_parameters(self):
        """Bug 554976. Make sure when we redirect, we preserve our query
        strings."""
        url = u'/users/login?to=/en-US/firefox/users/edit'
        r = self.client.get(url, follow=True)
        self.assert3xx(r, '/en-US/firefox' + url, status_code=301)

    def test_reviews(self):
        response = self.client.get('/reviews/display/4', follow=True)
        self.assert3xx(response, '/en-US/firefox/addon/a4/reviews/',
                       status_code=301)

    def test_browse(self):
        response = self.client.get('/browse/type:3', follow=True)
        self.assert3xx(response, '/en-US/firefox/language-tools/',
                       status_code=301)

        response = self.client.get('/browse/type:2', follow=True)
        self.assert3xx(response, '/en-US/firefox/complete-themes/',
                       status_code=301)

        # Drop the category.
        response = self.client.get('/browse/type:2/cat:all', follow=True)
        self.assert3xx(response, '/en-US/firefox/complete-themes/',
                       status_code=301)

    def test_accept_language(self):
        """
        Given an Accept Language header, do the right thing.  See bug 439568
        for juicy details.
        """

        response = self.client.get('/', follow=True, HTTP_ACCEPT_LANGUAGE='de')
        self.assert3xx(response, '/de/firefox/', status_code=301)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='en-us, de')
        self.assert3xx(response, '/en-US/firefox/', status_code=301)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='fr, en')
        self.assert3xx(response, '/fr/firefox/', status_code=301)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt-XX, xx, yy')
        self.assert3xx(response, '/pt-PT/firefox/', status_code=301)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt')
        self.assert3xx(response, '/pt-PT/firefox/', status_code=301)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt, de')
        self.assert3xx(response, '/pt-PT/firefox/', status_code=301)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='pt-XX, xx, de')
        self.assert3xx(response, '/pt-PT/firefox/', status_code=301)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='xx, yy, zz')
        self.assert3xx(response, '/en-US/firefox/', status_code=301)

        response = self.client.get(
            '/', follow=True,
            HTTP_ACCEPT_LANGUAGE='some,thing-very;very,,,broken!\'jj')
        self.assert3xx(response, '/en-US/firefox/', status_code=301)

        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='en-us;q=0.5, de')
        self.assert3xx(response, '/de/firefox/', status_code=301)

    def test_users(self):
        response = self.client.get('/users/info/1', follow=True)
        self.assert3xx(response, '/en-US/firefox/user/1/',
                       status_code=301)

    def test_extension_sorting(self):
        r = self.client.get('/browse/type:1?sort=updated', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/?sort=updated',
                       status_code=301)
        r = self.client.get('/browse/type:1?sort=name', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/?sort=name',
                       status_code=301)
        r = self.client.get('/browse/type:1?sort=newest', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/?sort=created',
                       status_code=301)
        r = self.client.get('/browse/type:1?sort=weeklydownloads', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/?sort=popular',
                       status_code=301)
        r = self.client.get('/browse/type:1?sort=averagerating', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/?sort=rating',
                       status_code=301)
        # If we don't recognize the sort, they get nothing.
        r = self.client.get('/browse/type:1?sort=xxx', follow=True)
        self.assert3xx(r, '/en-US/firefox/extensions/',
                       status_code=301)

        Category.objects.create(pk=12, slug='woo', type=amo.ADDON_EXTENSION,
                                application=amo.FIREFOX.id, count=1, weight=0)
        r = self.client.get('/browse/type:1/cat:12?sort=averagerating',
                            follow=True)
        url, code = r.redirect_chain[-1]
        assert code == 301
        assert url.endswith('/en-US/firefox/extensions/woo/?sort=rating')

    def test_addons_versions(self):
        r = self.client.get('/addons/versions/4', follow=True)
        self.assert3xx(r, '/en-US/firefox/addon/a4/versions/', status_code=301)

    def test_addons_versions_rss(self):
        r = self.client.get('/addons/versions/4/format:rss', follow=True)
        self.assert3xx(r, '/en-US/firefox/addon/4/versions/format:rss',
                       status_code=301)

    def test_addons_reviews_rss(self):
        r = self.client.get('/addons/reviews/4/format:rss', follow=True)
        self.assert3xx(r, '/en-US/firefox/addon/4/reviews/format:rss',
                       status_code=301)


class TestPersonaRedirect(TestCase):
    fixtures = ['addons/persona']

    def test_persona_redirect(self):
        """`/persona/\d+` should go to `/addon/\d+`."""
        r = self.client.get('/persona/813', follow=True)
        self.assert3xx(r, '/en-US/firefox/addon/a15663/', status_code=301)

    def test_persona_redirect_addon_no_exist(self):
        """When the persona exists but not its addon, throw a 404."""
        # Got get shady to separate Persona/Addons.
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SET FOREIGN_KEY_CHECKS = 0;
                    UPDATE personas SET addon_id=123 WHERE persona_id=813;
                    SET FOREIGN_KEY_CHECKS = 1;
                """)
            r = self.client.get('/persona/813', follow=True)
            assert r.status_code == 404
        finally:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SET FOREIGN_KEY_CHECKS = 0;
                    UPDATE personas SET addon_id=15663 WHERE persona_id=813;
                    SET FOREIGN_KEY_CHECKS = 1;
                """)
