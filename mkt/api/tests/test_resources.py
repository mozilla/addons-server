import json

from nose.tools import eq_
from django.core.urlresolvers import reverse

import mkt
from mkt.api.tests.test_oauth import RestOAuth


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
