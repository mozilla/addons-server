from decimal import Decimal
import json

from django.conf import settings
from django.core import mail

from mock import patch
from nose.tools import eq_

from market.models import Price, PriceCurrency
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.site.fixtures import fixture
from stats.models import Contribution


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
        res = self.client.get(self.list_url + ({'provider': 'bango'},))
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

    def test_has_cors(self):
        res = self.client.get(self.get_url)
        eq_(res['Access-Control-Allow-Origin'], '*')
        eq_(res['Access-Control-Allow-Methods'], 'GET, OPTIONS')

    @patch('mkt.webpay.resources.PriceResource.dehydrate_prices')
    def test_other_cors(self, prices):
        prices.side_effect = ValueError
        res = self.client.get(self.get_url)
        eq_(res.status_code, 500)
        eq_(res['Access-Control-Allow-Origin'], '*')
        eq_(res['Access-Control-Allow-Methods'], 'GET, OPTIONS')


@patch.object(settings, 'SITE_URL', 'http://api/')
class TestNotification(BaseOAuth):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestNotification, self).setUp(api_name='webpay')
        self.grant_permission(self.profile, 'Transaction:NotifyFailure')
        self.contribution = Contribution.objects.create(addon_id=337141,
                                                        uuid='sample:uuid')
        self.list_url = ('api_dispatch_list', {'resource_name': 'failure'})
        self.get_url = ['api_dispatch_detail',
                        {'resource_name': 'failure',
                         'pk': self.contribution.pk}]

    def test_list_allowed(self):
        self._allowed_verbs(self.get_url, ['patch'])

    def test_notify(self):
        url = 'https://someserver.com'
        res = self.client.patch(self.get_url,
                                data=json.dumps({'url': url,  'attempts': 5}))
        eq_(res.status_code, 202)
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        assert url in msg.body
        eq_(msg.recipients(), [u'steamcube@mozilla.com'])

    def test_no_permission(self):
        self.profile.groups.all().delete()
        res = self.client.patch(self.get_url, data=json.dumps({}))
        eq_(res.status_code, 401)

    def test_missing(self):
        res = self.client.patch(self.get_url, data=json.dumps({}))
        eq_(res.status_code, 400)

    def test_not_there(self):
        self.get_url[1]['pk'] += 1
        res = self.client.patch(self.get_url, data=json.dumps({}))
        eq_(res.status_code, 404)

    def test_no_uuid(self):
        self.contribution.update(uuid=None)
        res = self.client.patch(self.get_url, data=json.dumps({}))
        eq_(res.status_code, 404)
