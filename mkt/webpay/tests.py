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

    def test_list_allowed(self):
        self._allowed_verbs(self.list_url, ['get'])
        self._allowed_verbs(self.get_url, ['get'])

    def test_list(self):
        res = self.client.get(self.list_url)
        eq_(json.loads(res.content)['meta']['total_count'], 1)

    def test_prices(self):
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['name'], 'tier 1')
        eq_(len(data['prices']), 2)
        eq_(data['prices'][1], {'currency': 'CAD', 'amount': '3.00'})
