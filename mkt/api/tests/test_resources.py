import json

from mock import patch
from nose import SkipTest
from nose.tools import eq_, ok_

from django.conf import settings
from django.core.urlresolvers import reverse
from django.http import HttpRequest
from django.test.utils import override_settings

import mkt
from mkt.api.tests.test_oauth import RestOAuth
from mkt.api.resources import ErrorViewSet


class TestErrorService(RestOAuth):
    def setUp(self):
        if not settings.ENABLE_API_ERROR_SERVICE:
            # Because this service is activated in urls, you can't reliably
            # test it if the setting is False, because you'd need to force
            # django to re-parse urls before and after the test.
            raise SkipTest()
        super(TestErrorService, self).setUp()
        self.url = reverse('error-list')

    def verify_exception(self, got_request_exception):
        exception_handler_args = got_request_exception.send.call_args
        eq_(exception_handler_args[0][0], ErrorViewSet)
        eq_(exception_handler_args[1]['request'].path, self.url)
        ok_(isinstance(exception_handler_args[1]['request'], HttpRequest))

    @override_settings(DEBUG=False)
    @patch('mkt.api.exceptions.got_request_exception')
    def test_error_service_debug_false(self, got_request_exception):
        res = self.client.get(self.url)
        data = json.loads(res.content)
        eq_(data.keys(), ['detail'])
        eq_(data['detail'], 'Internal Server Error')
        self.verify_exception(got_request_exception)

    @override_settings(DEBUG=True)
    @patch('mkt.api.exceptions.got_request_exception')
    def test_error_service_debug_true(self, got_request_exception):
        res = self.client.get(self.url)
        data = json.loads(res.content)
        eq_(set(data.keys()), set(['detail', 'error_message', 'traceback']))
        eq_(data['detail'], 'Internal Server Error')
        eq_(data['error_message'], 'This is a test.')
        self.verify_exception(got_request_exception)


class TestConfig(RestOAuth):

    def setUp(self):
        super(TestConfig, self).setUp()
        self.url = reverse('site-config')

    def testConfig(self):
        self.create_switch('allow-refund')
        res = self.anon.get(self.url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['settings']['SITE_URL'], 'http://testserver')
        eq_(data['flags']['allow-refund'], True)

    def test_cors(self):
        self.assertCORS(self.anon.get(self.url), 'get')


class TestRegion(RestOAuth):
    def test_list(self):
        res = self.anon.get(reverse('regions-list'))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        for row in data['objects']:
            region = mkt.regions.REGIONS_DICT.get(row['slug'])
            eq_(row['name'], region.name)
            eq_(row['slug'], region.slug)
            eq_(row['id'], region.id)
            eq_(row['default_currency'], region.default_currency)
            eq_(row['default_language'], region.default_language)
            if region.ratingsbody:
                eq_(row['ratingsbody'], region.ratingsbody.name)
            else:
                eq_(row['ratingsbody'], None)
        eq_(len(data['objects']), len(mkt.regions.REGIONS_DICT))
        eq_(data['meta']['total_count'], len(mkt.regions.REGIONS_DICT))

    def test_detail(self):
        res = self.anon.get(reverse('regions-detail', kwargs={'pk': 'br'}))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        region = mkt.regions.REGIONS_DICT['br']
        eq_(data['name'], region.name)
        eq_(data['slug'], region.slug)
        eq_(data['id'], region.id)
        eq_(data['default_currency'], region.default_currency)
        eq_(data['default_language'], region.default_language)
        eq_(data['ratingsbody'], region.ratingsbody.name)


class TestCarrier(RestOAuth):
    def test_list(self):
        res = self.anon.get(reverse('carriers-list'))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        for row in data['objects']:
            region = mkt.carriers.CARRIER_MAP.get(row['slug'])
            eq_(row['name'], region.name)
            eq_(row['slug'], region.slug)
            eq_(row['id'], region.id)
        eq_(len(data['objects']), len(mkt.carriers.CARRIER_MAP))
        eq_(data['meta']['total_count'], len(mkt.carriers.CARRIER_MAP))

    def test_detail(self):
        res = self.anon.get(reverse('carriers-detail',
                                    kwargs={'pk': 'carrierless'}))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        carrier = mkt.carriers.CARRIER_MAP['carrierless']
        eq_(data['name'], carrier.name)
        eq_(data['slug'], carrier.slug)
        eq_(data['id'], carrier.id)
