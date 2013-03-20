import json

from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse


class TestHijackRedirectMiddleware(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.url = reverse('account.settings')

    def test_post_synchronous(self):
        res = self.client.post(self.url, {'display_name': 'omg'})
        self.assert3xx(res, self.url)
        assert res['Location']
        assert 'X-URI' not in res

    def test_unhijacked_ajax(self):
        res = self.client.post_ajax(self.url, {'display_name': 'omg'})
        self.assert3xx(res, self.url)

    def test_post_ajax(self):
        res = self.client.post_ajax(self.url, {'display_name': 'omg',
                                               '_hijacked': 'true'})
        eq_(res.status_code, 200)
        eq_(json.loads(pq(res.content)('#page').attr('data-context'))['uri'],
            self.url)
        assert 'Location' not in res
        assert res['X-URI']


class TestVaryOnAjaxMiddlware(amo.tests.TestCase):

    def test_xrequestedwith(self):
        r = self.client.get('/')
        assert 'X-Requested-With' in r['vary'].split(', ')
