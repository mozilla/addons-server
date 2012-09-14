import calendar
import json
import time
import urlparse

from django.conf import settings

import fudge
from fudge.inspector import arg
import jwt
import mock
from mock import Mock
from moz_inapp_pay.exc import RequestExpired
from moz_inapp_pay.verify import verify_claims, verify_keys
from nose.exc import SkipTest
from nose.tools import eq_, raises

import amo
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from stats.models import Contribution

from .test_views import PurchaseTest
from .samples import non_existant_pay


@mock.patch.object(settings, 'SECLUSION_HOSTS', ['host'])
class TestPurchase(PurchaseTest):

    def setUp(self):
        super(TestPurchase, self).setUp()
        self.prepare_pay = reverse('bluevia.prepare_pay',
                                   kwargs={'app_slug': self.addon.app_slug})
        self.create_flag(name='solitude-payments')

    def _req(self, method, url):
        req = getattr(self.client, method)
        resp = req(url)
        eq_(resp.status_code, 200)
        eq_(resp['content-type'], 'application/json')
        return json.loads(resp.content)

    def get(self, url, **kw):
        return self._req('get', url, **kw)

    def post(self, url, **kw):
        return self._req('post', url, **kw)

    def test_prepare_pay(self):#, api_post, create_seller):

        def good_data(da):
            da = json.loads(da)
            # TODO(Kumar) fix this when we have default currencies (bug 777747)
            eq_(da['currency'], 'USD')
            eq_(da['typ'], 'tu.com/payments/inapp/v1')
            eq_(da['aud'], 'tu.com')
            eq_(da['amount'], str(self.price.price))
            eq_(da['app_name'], unicode(self.addon.name))
            eq_(da['app_description'], unicode(self.addon.description))
            eq_(da['postback_url'],
                absolutify(reverse('bluevia.postback')))
            eq_(da['chargeback_url'],
                absolutify(reverse('bluevia.chargeback')))
            pd = urlparse.parse_qs(da['product_data'])
            assert 'contrib_uuid' in pd, 'Unexpected: %s' % pd
            eq_(pd['addon_id'][0], str(self.addon.pk))
            return True

        # Sample of BlueVia JWT but not complete.
        data = self.post(self.prepare_pay)
        cn = Contribution.objects.get()
        eq_(cn.type, amo.CONTRIB_PENDING)
        eq_(cn.user, self.user)
        eq_(cn.price_tier, self.price)
        eq_(jwt.decode(data['blueviaJWT'].encode('ascii'),
                       verify=False)['typ'], 'tu.com/payments/inapp/v1')

    def test_require_login(self):
        self.client.logout()
        resp = self.client.post(self.prepare_pay)
        self.assertLoginRequired(resp)

    def test_pay_status(self):
        uuid_ = '<returned from prepare-pay>'
        cn = Contribution.objects.create(addon_id=self.addon.id,
                                         amount=self.price.price,
                                         uuid=uuid_,
                                         type=amo.CONTRIB_PENDING,
                                         user=self.user)
        data = self.get(reverse('bluevia.pay_status',
                                args=[self.addon.app_slug, uuid_]))
        eq_(data['status'], 'incomplete')

        cn.update(type=amo.CONTRIB_PURCHASE)
        data = self.get(reverse('bluevia.pay_status',
                                args=[self.addon.app_slug, uuid_]))
        eq_(data['status'], 'complete')

    def test_status_for_purchases_only(self):
        uuid_ = '<returned from prepare-pay>'
        Contribution.objects.create(addon_id=self.addon.id,
                                    amount=self.price.price,
                                    uuid=uuid_,
                                    type=amo.CONTRIB_PURCHASE,
                                    user=self.user)
        self.client.logout()
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        data = self.get(reverse('bluevia.pay_status',
                                args=[self.addon.app_slug, uuid_]))
        eq_(data['status'], 'incomplete')

    def test_pay_status_for_unknown_contrib(self):
        data = self.get(reverse('bluevia.pay_status',
                                args=[self.addon.app_slug, '<garbage>']))
        eq_(data['status'], 'incomplete')


class TestPurchaseJWT(PurchaseTest):

    def setUp(self):
        super(TestPurchaseJWT, self).setUp()
        self.prepare_pay = reverse('bluevia.prepare_pay',
                                   kwargs={'app_slug': self.addon.app_slug})
        # This test relies on *not* setting the solitude-payments flag.

    def pay_jwt(self, lang=None):
        if not lang:
            lang = 'en-US'
        resp = self.client.post(self.prepare_pay,
                                HTTP_ACCEPT_LANGUAGE=lang)
        return json.loads(resp.content)['blueviaJWT']

    def pay_jwt_dict(self, lang=None):
        return jwt.decode(str(self.pay_jwt(lang=lang)), verify=False)

    def test_claims(self):
        verify_claims(self.pay_jwt_dict())

    def test_keys(self):
        verify_keys(self.pay_jwt_dict(),
                    ('iss',
                     'typ',
                     'aud',
                     'iat',
                     'exp',
                     'request.name',
                     'request.description',
                     'request.price',
                     'request.defaultPrice',
                     'request.postbackURL',
                     'request.chargebackURL',
                     'request.productData'))

    def test_prices(self):
        data = self.pay_jwt_dict()
        prices = sorted(data['request']['price'],
                        key=lambda p: p['currency'])

        eq_(prices[0], {'currency': 'BRL', 'amount': '0.50'})
        eq_(prices[1], {'currency': 'CAD', 'amount': '3.01'})
        eq_(prices[2], {'currency': 'EUR', 'amount': '5.01'})
        eq_(prices[3], {'currency': 'USD', 'amount': '0.99'})
        eq_(data['request']['defaultPrice'], 'USD')

    @mock.patch.object(settings, 'REGION_STORES', True)
    def test_brl_for_brazil(self):
        data = self.pay_jwt_dict(lang='pt-BR')
        eq_(data['request']['defaultPrice'], 'BRL')

    @mock.patch.object(settings, 'REGION_STORES', True)
    def test_usd_for_usa(self):
        data = self.pay_jwt_dict(lang='en-US')
        eq_(data['request']['defaultPrice'], 'USD')


@mock.patch.object(settings, 'SECLUSION_HOSTS', ['host'])
@mock.patch('mkt.purchase.bluevia.tasks')
class TestPostback(PurchaseTest):

    def setUp(self):
        super(TestPostback, self).setUp()
        self.client.logout()
        self.contrib = Contribution.objects.create(
                                        addon_id=self.addon.id,
                                        amount=self.price.price,
                                        uuid='<some uuid>',
                                        type=amo.CONTRIB_PENDING,
                                        user=self.user)
        self.bluevia_dev_id = '<stored in solitude>'
        self.bluevia_dev_secret = '<stored in solitude>'

    def post(self, req=None):
        if not req:
            req = self.jwt()
        return self.client.post(reverse('bluevia.postback'),
                                data=req, content_type='text/plain')

    def jwt_dict(self, expiry=3600, issued_at=None, contrib_uuid=None):
        if not issued_at:
            issued_at = calendar.timegm(time.gmtime())
        if not contrib_uuid:
            contrib_uuid = self.contrib.uuid
        return {'iss': 'tu.com',
                'aud': self.bluevia_dev_id,
                'typ': 'tu.com/payments/inapp/v1',
                'iat': issued_at,
                'exp': issued_at + expiry,
                'request': {
                    'name': 'Some App',
                    'description': 'fantastic app',
                    'price': '0.99',
                    'currencyCode': 'USD',
                    'postbackURL': '/postback',
                    'chargebackURL': '/chargeback',
                    'productData': 'contrib_uuid=%s' % contrib_uuid
                },
                'response': {
                    'transactionID': '<BlueVia-trans-id>'
                }}

    def jwt(self, req=None, **kw):
        if not req:
            req = self.jwt_dict(**kw)
        return jwt.encode(req, self.bluevia_dev_secret)

    @fudge.patch('lib.crypto.bluevia.jwt.decode')
    def test_valid(self, tasks, decode):
        jwt_dict = self.jwt_dict()
        jwt_encoded = self.jwt(req=jwt_dict)
        decode.expects_call().returns(jwt_dict)
        resp = self.post(req=jwt_encoded)
        eq_(resp.status_code, 200)
        eq_(resp.content, '<BlueVia-trans-id>')
        cn = Contribution.objects.get(pk=self.contrib.pk)
        eq_(cn.type, amo.CONTRIB_PURCHASE)
        eq_(cn.bluevia_transaction_id, '<BlueVia-trans-id>')
        # This verifies that we notify the downstream app
        # using the same exact JWT.
        tasks.purchase_notify.delay.assert_called_with(jwt_encoded, cn.pk)

    def test_invalid(self, tasks):
        resp = self.post()
        eq_(resp.status_code, 400)
        cn = Contribution.objects.get(pk=self.contrib.pk)
        eq_(cn.type, amo.CONTRIB_PENDING)

    @raises(RequestExpired)
    @fudge.patch('lib.crypto.bluevia.jwt.decode')
    def test_invalid_claim(self, tasks, decode):
        iat = calendar.timegm(time.gmtime()) - 3601  # too old
        decode.expects_call().returns(self.jwt_dict(issued_at=iat))
        self.post()

    @raises(LookupError)
    @fudge.patch('mkt.purchase.bluevia.parse_from_bluevia')
    def test_unknown_contrib(self, tasks, parse_from_bluevia):
        parse_from_bluevia.expects_call().returns(non_existant_pay)
        self.post()
