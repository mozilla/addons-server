import json

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo.tests
from amo.urlresolvers import reverse

import mkt
from mkt.carriers import set_carrier
from mkt.site.fixtures import fixture
from mkt.fragments.middleware import HijackRedirectMiddleware


class TestHijackRedirectMiddleware(amo.tests.TestCase):
    fixtures = fixture('user_999')

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

    @mock.patch('mkt.fragments.middleware.resolve')
    def test_post_ajax_carrier_url(self, resolve_mock):
        """
        Previously the URL was getting improperly munged because we thought
        there was a /<carrier>/ URL prefix if there was a carrier set. This
        should never raise a `Resolver404` (which means the URL was bad).
        """

        set_carrier(mkt.carriers.TELEFONICA.slug)

        # This is the location to which we are redirecting.
        location = reverse('ratings.list', args=['omg-yes'])

        # Mock away.
        request = mock.Mock(method='POST', POST={'_hijacked': 'true'}, META={})
        response = mock.Mock(status_code=302)
        response.__getitem__ = lambda self, header: location
        # I care only about resolving the URL. I don't care about the view.
        resolve_mock.func = mock.Mock()

        HijackRedirectMiddleware().process_response(request, response)

        resolve_mock.assert_called_with(location)


class TestVaryOnAjaxMiddlware(amo.tests.TestCase):

    def test_xrequestedwith(self):
        r = self.client.get('/')
        assert 'X-Requested-With' in r['vary'].split(', ')
