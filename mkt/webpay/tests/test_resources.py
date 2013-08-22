import json
from decimal import Decimal
import jwt

from django.core import mail

from mock import patch
from nose.tools import eq_, ok_
from waffle.models import Flag

from amo import CONTRIB_PENDING, CONTRIB_PURCHASE
from amo.tests import TestCase
from amo.urlresolvers import reverse
from constants.payments import PROVIDER_BANGO
from market.models import Price, PriceCurrency
from users.models import UserProfile

from mkt.api.base import get_url, list_url
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.constants import regions
from mkt.purchase.tests.utils import PurchaseTest
from mkt.site.fixtures import fixture
from mkt.webpay.models import ProductIcon
from stats.models import Contribution


class TestPrepare(PurchaseTest, BaseOAuth):
    fixtures = fixture('webapp_337141', 'user_2519', 'prices')

    def setUp(self):
        BaseOAuth.setUp(self, api_name='webpay')
        self.create_switch('marketplace')
        self.create_switch('allow-paid-app-search')
        self.list_url = list_url('prepare')
        self.user = UserProfile.objects.get(pk=2519)

    def test_allowed(self):
        self._allowed_verbs(self.list_url, ['post'])

    def test_anon(self):
        eq_(self.anon.post(self.list_url, data={}).status_code, 401)

    def test_good(self):
        self.setup_base()
        self.setup_package()
        res = self.client.post(self.list_url, data=json.dumps({'app': 337141}))
        contribution = Contribution.objects.get()
        eq_(res.status_code, 201)
        eq_(res.json['contribStatusURL'], reverse('api_dispatch_detail',
            kwargs={'api_name': 'webpay', 'resource_name': 'status',
                    'uuid': contribution.uuid}))
        ok_(res.json['webpayJWT'])

    @patch('mkt.webapps.models.Webapp.has_purchased')
    def test_already_purchased(self, has_purchased):
        has_purchased.return_value = True
        self.setup_base()
        self.setup_package()
        res = self.client.post(self.list_url, data=json.dumps({'app': 337141}))
        eq_(res.status_code, 409)
        eq_(res.content, '{"reason": "Already purchased app."}')

    def _post(self):
        return self.client.post(self.list_url,
                                data=json.dumps({'app': 337141}))

    def test_bad_region(self):
        with self.settings(PURCHASE_ENABLED_REGIONS=[]):
            eq_(self._post().status_code, 403)

    def test_good_region(self):
        self.setup_base()
        self.setup_package()
        with self.settings(PURCHASE_ENABLED_REGIONS=[2]):
            eq_(self._post().status_code, 201)

    def test_waffle_fallback(self):
        self.setup_base()
        self.setup_package()
        flag = self.create_flag('allow-paid-app-search', everyone=None)
        flag.users.add(self.user.user)
        with self.settings(PURCHASE_ENABLED_REGIONS=[]):
            eq_(self._post().status_code, 201)


class TestStatus(BaseOAuth):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestStatus, self).setUp(api_name='webpay')
        self.contribution = Contribution.objects.create(
            addon_id=337141, user_id=2519, type=CONTRIB_PURCHASE,
            uuid='some:uid')
        self.get_url = ('api_dispatch_detail', {
            'api_name': 'webpay', 'resource_name': 'status',
            'uuid': self.contribution.uuid})

    def test_allowed(self):
        self._allowed_verbs(self.get_url, ['get'])

    def test_get(self):
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        eq_(res.json['status'], 'complete')

    def test_no_contribution(self):
        self.contribution.delete()
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200, res.content)
        eq_(res.json['status'], 'incomplete', res.content)

    def test_incomplete(self):
        self.contribution.update(type=CONTRIB_PENDING)
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200, res.content)
        eq_(res.json['status'], 'incomplete', res.content)

    def test_no_purchase(self):
        self.contribution.addon.addonpurchase_set.get().delete()
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200, res.content)
        eq_(res.json['status'], 'incomplete', res.content)


class TestPrices(BaseOAuth):

    def make_currency(self, amount, tier, currency, region):
        return PriceCurrency.objects.create(price=Decimal(amount), tier=tier,
            currency=currency, provider=PROVIDER_BANGO, region=region.id)

    def setUp(self):
        super(TestPrices, self).setUp(api_name='webpay')
        self.price = Price.objects.create(name='1', price=Decimal(1))
        self.currency = self.make_currency(3, self.price, 'DE', regions.DE)
        self.us_currency = self.make_currency(3, self.price, 'USD', regions.US)
        self.list_url = list_url('prices')
        self.get_url = get_url('prices', self.price.pk)

        # If regions change, this will blow up.
        assert regions.BR.default_currency == 'BRL'

    def get_currencies(self, data):
        return [p['currency'] for p in data['prices']]

    def test_list_allowed(self):
        self._allowed_verbs(self.list_url, ['get'])
        self._allowed_verbs(self.get_url, ['get'])

    def test_single(self):
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        eq_(res.json['pricePoint'], '1')
        eq_(res.json['name'], 'Tier 1')
        # Ensure that price is in the JSON since solitude depends upon it.
        eq_(res.json['price'], '1.00')

    def test_price_point(self):
        res = self.client.get(self.list_url + ({'pricePoint': '1'},))
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 1)
        eq_(data['objects'][0]['pricePoint'], '1')

    def test_list(self):
        res = self.client.get(self.list_url)
        eq_(res.json['meta']['total_count'], 1)
        self.assertSetEqual(self.get_currencies(res.json['objects'][0]),
                            ['USD', 'DE'])

    def test_list_filtered(self):
        self.currency.update(provider=0)
        res = self.client.get(self.list_url + ({'provider': 'bango'},))
        eq_(self.get_currencies(res.json['objects'][0]), ['USD'])

    def test_prices(self):
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        self.assertSetEqual(self.get_currencies(res.json), ['USD', 'DE'])

    def test_prices_filtered(self):
        self.currency.update(provider=0)
        res = self.client.get(self.get_url + ({'provider': 'bango'},))
        eq_(res.status_code, 200)
        self.assertSetEqual(self.get_currencies(res.json), ['USD'])

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.get_url), 'get')

    @patch('mkt.webpay.resources.PriceResource.dehydrate_prices')
    def test_other_cors(self, prices):
        prices.side_effect = ValueError
        res = self.client.get(self.get_url)
        eq_(res.status_code, 500)
        self.assertCORS(res, 'get')

    def test_locale(self):
        self.make_currency(5, self.price, 'BRL', regions.BR)
        res = self.client.get(self.get_url, HTTP_ACCEPT_LANGUAGE='pt-BR')
        eq_(res.status_code, 200)
        eq_(res.json['localized']['locale'], 'R$5,00')

    def test_locale_list(self):
        # Check that for each price tier a different localisation is
        # returned.
        self.make_currency(2, self.price, 'BRL', regions.BR)
        price_two = Price.objects.create(name='2', price=Decimal(1))
        self.make_currency(12, price_two, 'BRL', regions.BR)

        res = self.client.get(self.list_url, HTTP_ACCEPT_LANGUAGE='pt-BR')
        eq_(res.status_code, 200)
        eq_(res.json['objects'][0]['localized']['locale'], 'R$2,00')
        eq_(res.json['objects'][1]['localized']['locale'], 'R$12,00')

    def test_no_locale(self):
        # This results in a region of BR and a currency of BRL. But there
        # isn't a price tier for that currency. So we don't know what to show.
        res = self.client.get(self.get_url, HTTP_ACCEPT_LANGUAGE='pt-BR')
        eq_(res.status_code, 200)
        eq_(res.json['localized'], {})


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
                                data=json.dumps({'url': url, 'attempts': 5}))
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


class TestProductIconResource(BaseOAuth):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestProductIconResource, self).setUp(api_name='webpay')
        self.list_url = list_url('product/icon')
        p = patch('mkt.webpay.resources.tasks.fetch_product_icon')
        self.fetch_product_icon = p.start()
        self.addCleanup(p.stop)
        self.data = {
            'ext_size': 128,
            'ext_url': 'http://someappnoreally.com/icons/icon_128.png',
            'size': 64
        }

    def post(self, data, with_perms=True):
        if with_perms:
            self.grant_permission(self.profile, 'ProductIcon:Create')
        return self.client.post(self.list_url, data=json.dumps(data))

    def test_list_allowed(self):
        self._allowed_verbs(self.list_url, ['get', 'post'])

    def test_missing_fields(self):
        res = self.post({'ext_size': 1})
        eq_(res.status_code, 400)

    def test_post(self):
        res = self.post(self.data)
        eq_(res.status_code, 202)
        self.fetch_product_icon.delay.assert_called_with(self.data['ext_url'],
                                                         self.data['ext_size'],
                                                         self.data['size'])

    def test_post_without_perms(self):
        res = self.post(self.data, with_perms=False)
        eq_(res.status_code, 401)

    def test_anon_get(self):
        data = {
            'ext_size': 128,
            'ext_url': 'http://someappnoreally.com/icons/icon_128.png',
            'size': 64,
            'format': 'png'
        }
        icon = ProductIcon.objects.create(**data)

        # We don't need to filter by these:
        data.pop('size')
        data.pop('format')
        res = self.anon.get(self.list_url, data=data)
        eq_(res.status_code, 200)

        ob = json.loads(res.content)['objects'][0]
        eq_(ob['url'], icon.url())


class TestSigCheck(TestCase):

    def test(self):
        key = 'marketplace'
        aud = 'webpay'
        secret = 'third door on the right'
        with self.settings(APP_PURCHASE_SECRET=secret,
                           APP_PURCHASE_KEY=key,
                           APP_PURCHASE_AUD=aud):
            res = self.client.post(reverse('webpay.sig_check'))
        eq_(res.status_code, 201, res)
        data = json.loads(res.content)
        req = jwt.decode(data['sig_check_jwt'].encode('ascii'), secret)
        eq_(req['iss'], key)
        eq_(req['aud'], aud)
        eq_(req['typ'], 'mozilla/payments/sigcheck/v1')
