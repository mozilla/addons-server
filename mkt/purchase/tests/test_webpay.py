import calendar
import json
import time
import urlparse

from django.conf import settings

import fudge
import jwt
import mock
from moz_inapp_pay.exc import RequestExpired
from moz_inapp_pay.verify import verify_claims, verify_keys
from nose.tools import eq_, raises

import amo
from amo.helpers import absolutify
from amo.tests import TestCase
from amo.urlresolvers import reverse
from stats.models import Contribution

from .test_views import PurchaseTest
from .samples import non_existant_pay


@mock.patch.object(settings, 'SOLITUDE_HOSTS', ['host'])
class TestPurchase(PurchaseTest):

    def setUp(self):
        super(TestPurchase, self).setUp()
        self.prepare_pay = reverse('webpay.prepare_pay',
                                   kwargs={'app_slug': self.addon.app_slug})
        self.create_flag(name='solitude-payments')
        self.setup_package()

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

    def test_prepare_pay(self):
        from mkt.purchase.webpay import make_ext_id
        data = self.post(self.prepare_pay)
        cn = Contribution.objects.get()
        eq_(cn.type, amo.CONTRIB_PENDING)
        eq_(cn.user, self.user)
        eq_(cn.price_tier, self.price)

        data = jwt.decode(data['webpayJWT'].encode('ascii'), verify=False)
        eq_(data['typ'], settings.APP_PURCHASE_TYP)
        eq_(data['aud'], settings.APP_PURCHASE_AUD)
        req = data['request']
        eq_(req['pricePoint'], self.price.pk)
        eq_(req['id'], make_ext_id(self.addon.pk))
        eq_(req['name'], unicode(self.addon.name))
        eq_(req['description'], unicode(self.addon.summary))
        eq_(req['postbackURL'],
            absolutify(reverse('webpay.postback')))
        eq_(req['chargebackURL'],
            absolutify(reverse('webpay.chargeback')))
        pd = urlparse.parse_qs(req['productData'])
        eq_(pd['contrib_uuid'][0], cn.uuid)
        eq_(pd['seller_uuid'][0], self.seller.uuid)
        eq_(pd['addon_id'][0], str(self.addon.pk))

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
        data = self.get(reverse('webpay.pay_status',
                                args=[self.addon.app_slug, uuid_]))
        eq_(data['status'], 'incomplete')

        cn.update(type=amo.CONTRIB_PURCHASE)
        data = self.get(reverse('webpay.pay_status',
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
        data = self.get(reverse('webpay.pay_status',
                                args=[self.addon.app_slug, uuid_]))
        eq_(data['status'], 'incomplete')

    def test_pay_status_for_unknown_contrib(self):
        data = self.get(reverse('webpay.pay_status',
                                args=[self.addon.app_slug, '<garbage>']))
        eq_(data['status'], 'incomplete')

    def test_strip_html(self):
        self.addon.summary = 'Some <a href="http://soso.com">site</a>'
        self.addon.save()
        data = self.post(self.prepare_pay)
        data = jwt.decode(data['webpayJWT'].encode('ascii'), verify=False)
        req = data['request']
        eq_(req['description'], 'Some site')


class TestPurchaseJWT(PurchaseTest):

    def setUp(self):
        super(TestPurchaseJWT, self).setUp()
        self.prepare_pay = reverse('webpay.prepare_pay',
                                   kwargs={'app_slug': self.addon.app_slug})
        # This test relies on *not* setting the solitude-payments flag.

    def pay_jwt(self, lang=None):
        if not lang:
            lang = 'en-US'
        resp = self.client.post(self.prepare_pay,
                                HTTP_ACCEPT_LANGUAGE=lang)
        return json.loads(resp.content)['webpayJWT']

    def pay_jwt_dict(self, lang=None):
        return jwt.decode(str(self.pay_jwt(lang=lang)), verify=False)

    def test_claims(self):
        self.setup_package()
        verify_claims(self.pay_jwt_dict())

    def test_keys(self):
        self.setup_package()
        verify_keys(self.pay_jwt_dict(),
                    ('iss',
                     'typ',
                     'aud',
                     'iat',
                     'exp',
                     'request.name',
                     'request.description',
                     'request.pricePoint',
                     'request.postbackURL',
                     'request.chargebackURL',
                     'request.productData'))


@mock.patch.object(settings, 'SOLITUDE_HOSTS', ['host'])
@mock.patch('mkt.purchase.webpay.tasks')
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
        self.webpay_dev_id = '<stored in solitude>'
        self.webpay_dev_secret = '<stored in solitude>'

    def post(self, req=None):
        if not req:
            req = self.jwt()
        return self.client.post(reverse('webpay.postback'),
                                data=req, content_type='text/plain')

    def jwt_dict(self, expiry=3600, issued_at=None, contrib_uuid=None):
        if not issued_at:
            issued_at = calendar.timegm(time.gmtime())
        if not contrib_uuid:
            contrib_uuid = self.contrib.uuid
        return {'iss': 'tu.com',
                'aud': self.webpay_dev_id,
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
        return jwt.encode(req, self.webpay_dev_secret)

    @fudge.patch('lib.crypto.webpay.jwt.decode')
    def test_valid(self, tasks, decode):
        jwt_dict = self.jwt_dict()
        jwt_encoded = self.jwt(req=jwt_dict)
        decode.expects_call().returns(jwt_dict)
        resp = self.post(req=jwt_encoded)
        eq_(resp.status_code, 200)
        eq_(resp.content, '<BlueVia-trans-id>')
        cn = Contribution.objects.get(pk=self.contrib.pk)
        eq_(cn.type, amo.CONTRIB_PURCHASE)
        # This verifies that we notify the downstream app
        # using the same exact JWT.
        tasks.purchase_notify.delay.assert_called_with(jwt_encoded, cn.pk)
        tasks.send_purchase_receipt.delay.assert_called_with(cn.pk)

    def test_invalid(self, tasks):
        resp = self.post()
        eq_(resp.status_code, 400)
        cn = Contribution.objects.get(pk=self.contrib.pk)
        eq_(cn.type, amo.CONTRIB_PENDING)

    @raises(RequestExpired)
    @fudge.patch('lib.crypto.webpay.jwt.decode')
    def test_invalid_claim(self, tasks, decode):
        iat = calendar.timegm(time.gmtime()) - 3601  # too old
        decode.expects_call().returns(self.jwt_dict(issued_at=iat))
        self.post()

    @raises(LookupError)
    @fudge.patch('mkt.purchase.webpay.parse_from_webpay')
    def test_unknown_contrib(self, tasks, parse_from_webpay):
        parse_from_webpay.expects_call().returns(non_existant_pay)
        self.post()


class TestExtId(TestCase):

    def setUp(self):
        from mkt.purchase.webpay import make_ext_id
        self.ext_id = make_ext_id

    def test_no_domain(self):
        with self.settings(DOMAIN=None):
            eq_(self.ext_id(123), 'marketplace-dev:123')

    def test_domain(self):
        with self.settings(DOMAIN='marketplace.allizom.org'):
            eq_(self.ext_id(123), 'marketplace:123')
