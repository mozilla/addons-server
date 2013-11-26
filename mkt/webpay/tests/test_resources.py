import json
from decimal import Decimal
import jwt

from django.conf import settings
from django.core import mail
from django.http import HttpRequest

from mock import patch
from nose.tools import eq_, ok_

from amo import CONTRIB_PENDING, CONTRIB_PURCHASE
from amo.tests import TestCase
from amo.urlresolvers import reverse
from constants.payments import PROVIDER_BANGO
from market.models import Price, PriceCurrency
from users.models import UserProfile, GroupUser

from mkt.api.tests.test_oauth import RestOAuth
from mkt.constants import regions
from mkt.purchase.tests.utils import PurchaseTest
from mkt.site.fixtures import fixture
from mkt.webpay.models import ProductIcon
from mkt.webpay.resources import PricesViewSet
from stats.models import Contribution


class TestPrepare(PurchaseTest, RestOAuth):
    fixtures = fixture('webapp_337141', 'user_2519', 'prices')

    def setUp(self):
        RestOAuth.setUp(self)  # Avoid calling PurchaseTest.setUp().
        self.user = UserProfile.objects.get(pk=2519)
        self.create_switch('marketplace')
        self.list_url = reverse('webpay-prepare')
        self.setup_base()
        self.setup_package()

    def _post(self, client=None, extra_headers=None):
        if client is None:
            client = self.client
        if extra_headers is None:
            extra_headers = {}
        return client.post(self.list_url, data=json.dumps({'app': 337141}),
                           **extra_headers)

    def test_allowed(self):
        self._allowed_verbs(self.list_url, ['post'])

    def test_anon(self):
        res = self._post(self.anon)
        eq_(res.status_code, 403)
        eq_(res.json,
            {'detail': 'Authentication credentials were not provided.'})

    def test_good(self, client=None, extra_headers=None):
        res = self._post(client=client, extra_headers=extra_headers)
        eq_(res.status_code, 201, res.content)
        contribution = Contribution.objects.get()
        eq_(res.json['contribStatusURL'],
            reverse('webpay-status', kwargs={'uuid': contribution.uuid}))
        ok_(res.json['webpayJWT'])

    @patch.object(settings, 'SECRET_KEY', 'gubbish')
    def test_good_shared_secret(self):
        # Like test_good, except we do shared secret auth manually.
        extra_headers = {
            'HTTP_AUTHORIZATION': 'mkt-shared-secret '
                                  'cfinke@m.com,56b6f1a3dd735d962c56'
                                  'ce7d8f46e02ec1d4748d2c00c407d75f0969d08bb'
                                  '9c68c31b3371aa8130317815c89e5072e31bb94b4'
                                  '121c5c165f3515838d4d6c60c4,165d631d3c3045'
                                  '458b4516242dad7ae'
        }
        self.user.update(email='cfinke@m.com')
        self.test_good(client=self.anon, extra_headers=extra_headers)

    @patch('mkt.webapps.models.Webapp.has_purchased')
    def test_already_purchased(self, has_purchased):
        has_purchased.return_value = True
        res = self._post()
        eq_(res.status_code, 409)
        eq_(res.json, {"reason": "Already purchased app."})

    def test_waffle_fallback(self):
        flag = self.create_flag('override-app-purchase', everyone=None)
        flag.users.add(self.user.user)
        with self.settings(PURCHASE_LIMITED=True):
            eq_(self._post().status_code, 201)


class TestStatus(RestOAuth):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestStatus, self).setUp()
        self.contribution = Contribution.objects.create(
            addon_id=337141, user_id=2519, type=CONTRIB_PURCHASE,
            uuid='some:uid')
        self.get_url = reverse('webpay-status',
                               kwargs={'uuid': self.contribution.uuid})

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

    def test_not_owner(self):
        userprofile2 = UserProfile.objects.get(pk=31337)
        self.contribution.update(user=userprofile2)
        res = self.client.get(self.get_url)
        eq_(res.status_code, 403, res.content)


class TestPrices(RestOAuth):

    def make_currency(self, amount, tier, currency, region):
        return PriceCurrency.objects.create(price=Decimal(amount), tier=tier,
            currency=currency, provider=PROVIDER_BANGO, region=region.id)

    def setUp(self):
        super(TestPrices, self).setUp()
        self.price = Price.objects.create(name='1', price=Decimal(1))
        self.currency = self.make_currency(3, self.price, 'DE', regions.DE)
        self.us_currency = self.make_currency(3, self.price, 'USD', regions.US)
        self.list_url = reverse('price-list')
        self.get_url = reverse('price-detail', kwargs={'pk': self.price.pk})

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

    def test_list_filtered_price_point(self):
        Price.objects.create(name='42', price=Decimal(42))
        res = self.client.get(self.list_url, {'pricePoint': '1'})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(data['meta']['total_count'], 1)
        eq_(data['objects'][0]['pricePoint'], '1')

    def test_list(self):
        res = self.client.get(self.list_url)
        eq_(res.json['meta']['total_count'], 1)
        self.assertSetEqual(self.get_currencies(res.json['objects'][0]),
                            ['USD', 'DE'])

    def test_list_filtered_provider(self):
        self.currency.update(provider=0)
        res = self.client.get(self.list_url, {'provider': 'bango'})
        eq_(self.get_currencies(res.json['objects'][0]), ['USD'])

    def test_prices(self):
        res = self.client.get(self.get_url)
        eq_(res.status_code, 200)
        self.assertSetEqual(self.get_currencies(res.json), ['USD', 'DE'])

    def test_prices_filtered_provider(self):
        self.currency.update(provider=0)
        res = self.client.get(self.get_url, {'provider': 'bango'})
        eq_(res.status_code, 200)
        self.assertSetEqual(self.get_currencies(res.json), ['USD'])

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.get_url), 'get')

    @patch('mkt.api.exceptions.got_request_exception')
    @patch('market.models.Price.prices')
    def test_other_cors(self, prices, got_request_exception):
        prices.side_effect = ValueError('The Price Is Not Right.')
        res = self.client.get(self.get_url)
        eq_(res.status_code, 500)
        self.assertCORS(res, 'get')
        exception_handler_args = got_request_exception.send.call_args
        eq_(exception_handler_args[0][0], PricesViewSet)
        eq_(exception_handler_args[1]['request'].path, self.get_url)
        ok_(isinstance(exception_handler_args[1]['request'], HttpRequest))

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


class TestNotification(RestOAuth):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestNotification, self).setUp()
        self.grant_permission(self.profile, 'Transaction:NotifyFailure')
        self.contribution = Contribution.objects.create(addon_id=337141,
                                                        uuid='sample:uuid')
        self.get_url = reverse('webpay-failurenotification',
                               kwargs={'pk': self.contribution.pk})
        self.data = {'url': 'https://someserver.com', 'attempts': 5}

    def test_list_allowed(self):
        self._allowed_verbs(self.get_url, ['patch'])

    def test_notify(self):
        res = self.client.patch(self.get_url, data=json.dumps(self.data))
        eq_(res.status_code, 202)
        eq_(len(mail.outbox), 1)
        msg = mail.outbox[0]
        assert self.data['url'] in msg.body
        eq_(msg.recipients(), [u'steamcube@mozilla.com'])

    def test_no_permission(self):
        GroupUser.objects.filter(user=self.profile).delete()
        res = self.client.patch(self.get_url,  data=json.dumps(self.data))
        eq_(res.status_code, 403)

    def test_missing(self):
        res = self.client.patch(self.get_url, data=json.dumps({}))
        eq_(res.status_code, 400)

    def test_not_there(self):
        self.get_url = reverse('webpay-failurenotification',
                               kwargs={'pk': self.contribution.pk + 42})
        res = self.client.patch(self.get_url, data=json.dumps(self.data))
        eq_(res.status_code, 404)

    def test_no_uuid(self):
        self.contribution.update(uuid=None)
        res = self.client.patch(self.get_url, data=json.dumps(self.data))
        eq_(res.status_code, 404)


class TestProductIconResource(RestOAuth):
    fixtures = fixture('webapp_337141', 'user_2519')

    def setUp(self):
        super(TestProductIconResource, self).setUp()
        self.list_url = reverse('producticon-list')
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
        eq_(res.status_code, 403)

    def test_anon_get_filtering(self):
        icon = ProductIcon.objects.create(**{
            'ext_size': 128,
            'ext_url': 'http://someappnoreally.com/icons/icon_128.png',
            'size': 64,
            'format': 'png'
        })
        extra_icon = ProductIcon.objects.create(**{
            'ext_size': 256,
            'ext_url': 'http://someappnoreally.com/icons/icon_256.png',
            'size': 64,
            'format': 'png'
        })
        res = self.anon.get(self.list_url)
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)

        res = self.anon.get(self.list_url, data={'ext_size': 128})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 1)
        eq_(data['objects'][0]['url'], icon.url())

        res = self.anon.get(self.list_url, data={'size': 64})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 2)

        res = self.anon.get(self.list_url,
            data={'ext_url': 'http://someappnoreally.com/icons/icon_256.png'})
        eq_(res.status_code, 200)
        data = json.loads(res.content)
        eq_(len(data['objects']), 1)
        eq_(data['objects'][0]['url'], extra_icon.url())


class TestSigCheck(TestCase):

    def test(self):
        key = 'marketplace'
        aud = 'webpay'
        secret = 'third door on the right'
        with self.settings(APP_PURCHASE_SECRET=secret,
                           APP_PURCHASE_KEY=key,
                           APP_PURCHASE_AUD=aud):
            res = self.client.post(reverse('webpay-sig_check'))
        eq_(res.status_code, 201, res)
        data = json.loads(res.content)
        req = jwt.decode(data['sig_check_jwt'].encode('ascii'), secret)
        eq_(req['iss'], key)
        eq_(req['aud'], aud)
        eq_(req['typ'], 'mozilla/payments/sigcheck/v1')
