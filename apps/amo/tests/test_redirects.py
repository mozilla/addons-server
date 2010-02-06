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
