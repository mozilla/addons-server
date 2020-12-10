# -*- coding: utf-8 -*-
"""Check all our redirects from remora to zamboni."""
from olympia.amo.tests import TestCase


class TestRedirects(TestCase):
    def test_accept_language(self):
        """
        Given an Accept Language header, do the right thing.  See bug 439568
        for juicy details.
        """

        response = self.client.get(
            '/developers', follow=True, HTTP_ACCEPT_LANGUAGE='de'
        )
        self.assert3xx(response, '/de/developers/', status_code=302)

        response = self.client.get(
            '/developers', follow=True, HTTP_ACCEPT_LANGUAGE='en-us, de'
        )
        self.assert3xx(response, '/en-US/developers/', status_code=302)

        response = self.client.get(
            '/developers', follow=True, HTTP_ACCEPT_LANGUAGE='fr, en'
        )
        self.assert3xx(response, '/fr/developers/', status_code=302)

        response = self.client.get(
            '/developers', follow=True, HTTP_ACCEPT_LANGUAGE='pt-XX, xx, yy'
        )
        self.assert3xx(response, '/pt-PT/developers/', status_code=302)

        response = self.client.get(
            '/developers', follow=True, HTTP_ACCEPT_LANGUAGE='pt'
        )
        self.assert3xx(response, '/pt-PT/developers/', status_code=302)

        response = self.client.get(
            '/developers', follow=True, HTTP_ACCEPT_LANGUAGE='pt, de'
        )
        self.assert3xx(response, '/pt-PT/developers/', status_code=302)

        response = self.client.get(
            '/developers', follow=True, HTTP_ACCEPT_LANGUAGE='pt-XX, xx, de'
        )
        self.assert3xx(response, '/pt-PT/developers/', status_code=302)

        response = self.client.get(
            '/developers', follow=True, HTTP_ACCEPT_LANGUAGE='xx, yy, zz'
        )
        self.assert3xx(response, '/en-US/developers/', status_code=302)

        response = self.client.get(
            '/developers',
            follow=True,
            HTTP_ACCEPT_LANGUAGE="some,thing-very;very,,,broken!'jj",
        )
        self.assert3xx(response, '/en-US/developers/', status_code=302)

        response = self.client.get(
            '/developers', follow=True, HTTP_ACCEPT_LANGUAGE='en-us;q=0.5, de'
        )
        self.assert3xx(response, '/de/developers/', status_code=302)

    def test_legacy_discovery_to_mozilla_new_page(self):
        response = self.client.get('/en-US/firefox/discovery/', follow=False)
        self.assertRedirects(
            response,
            'https://www.mozilla.org/firefox/new/',
            status_code=301,
            fetch_redirect_response=False,
        )
