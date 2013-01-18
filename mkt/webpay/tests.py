from decimal import Decimal
import json

from django.conf import settings

from mock import patch
from nose.tools import eq_

from market.models import Price, PriceCurrency
from mkt.api.tests.test_oauth import BaseOAuth


@patch.object(settings, 'SITE_URL', 'http://api/')
class TestPrices(BaseOAuth):

    def setUp(self):
        super(TestPrices, self).setUp(api_name='webpay')
        self.price = Price.objects.create(name='tier 1', price=Decimal(1))
        self.currency = PriceCurrency.objects.create(price=Decimal(3),
                                                     tier_id=self.price.pk,
                                                     currency='CAD')
        self.list_url = ('api_dispatch_list', {'resource_name': 'prices'})
        self.get_url = ('api_dispatch_detail',
                        {'resource_name': 'prices', 'pk': self.price.pk})

    def get_currencies(self, data):
        return [p['currency'] for p in data['prices']]

    def test_list_allowed(self):
        self._allowed_verbs(self.list_url, ['get'])
        self._allowed_verbs(self.get_url, ['get'])

    def test_list(self):
        res = self.client.get(self.list_url)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 1)
        self.assertSetEqual(self.get_currencies(data['objects'][0]),
                            ['USD', 'CAD'])

    @patch('market.models.PROVIDER_CURRENCIES', {'bango': ['USD', 'EUR']})
    def test_list_filtered(self):
        res = self.client.get(self.get_url + ({'provider': 'bango'},))
        data = json.loads(res.content)
        self.assertSetEqual(self.get_currencies(data['objects'][0]), ['USD'])

    def test_prices(self):
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        self.assertSetEqual(self.get_currencies(data), ['USD', 'CAD'])

    @patch('market.models.PROVIDER_CURRENCIES', {'bango': ['USD', 'EUR']})
    def test_prices_filtered(self):
        res = self.client.get(self.get_url + ({'provider': 'bango'},))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        self.assertSetEqual(self.get_currencies(data), ['USD'])
