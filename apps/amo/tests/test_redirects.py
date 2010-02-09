"""Check all our redirects from remora to zamboni."""
from django import test

from nose.tools import eq_

from amo.urlresolvers import reverse


class TestRedirects(test.TestCase):

    fixtures = ['amo/test_redirects']

    def test_reviews(self):
        response = self.client.get('/reviews/display/4', follow=True)
        self.assertRedirects(response, '/en-US/firefox/addon/4/reviews/',
                             status_code=301)

    def test_browse(self):
        response = self.client.get('/browse/type:3', follow=True)
        self.assertRedirects(response, '/en-US/firefox/language-tools',
                             status_code=301)

    def test_accept_language(self):
        """
        Given an Accept Language header with a preference for German we should
        redirect to the /de/firefox site.
        """
        response = self.client.get('/', follow=True, HTTP_ACCEPT_LANGUAGE='de')
        self.assertRedirects(response, '/de/firefox/', status_code=301)

        # test that en-us->en-US
        response = self.client.get('/', follow=True,
                                   HTTP_ACCEPT_LANGUAGE='en-us,de;q=0.5')
        self.assertRedirects(response, '/en-US/firefox/', status_code=301)
