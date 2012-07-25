import calendar
import json
import time

from django.conf import settings

import fudge
from fudge.inspector import arg
import jwt
import mock
from mock import Mock
from nose.tools import eq_

import amo
from amo.helpers import absolutify
from amo.urlresolvers import reverse
from stats.models import Contribution

from .test_views import PurchaseTest


@mock.patch.object(settings, 'SECLUSION_HOSTS', ['host'])
class TestPurchase(PurchaseTest):

    def setUp(self):
        super(TestPurchase, self).setUp()
        self.prepare_pay = reverse('bluevia.prepare_pay',
                                   kwargs={'app_slug': self.addon.app_slug})

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

    @fudge.patch('lib.pay_server.base.requests.post')
    def test_prepare_pay(self, api_post):

        def good_data(da):
            da = json.loads(da)
            # TODO(Kumar) fix this when we have default currencies (bug 777747)
            eq_(da['currency'], 'USD')
            eq_(da['amount'], str(self.price.price))
            eq_(da['app_name'], unicode(self.addon.name))
            eq_(da['app_description'], unicode(self.addon.description))
            eq_(da['postback_url'],
                absolutify(reverse('bluevia.postback')))
            eq_(da['chargeback_url'],
                absolutify(reverse('bluevia.chargeback')))
            assert 'contrib_uuid' in da
            return True

        # Sample of BlueVia JWT but not complete.
        bluevia_jwt = {'typ': 'tu.com/payments/inapp/v1'}

        (api_post.expects_call()
                 .with_args(arg.any(), data=arg.passes_test(good_data),
                            timeout=arg.any(), headers=arg.any())
                 .returns(Mock(text=json.dumps(bluevia_jwt),
                               status_code=200)))
        data = self.post(self.prepare_pay)
        cn = Contribution.objects.get(uuid=data['contrib_uuid'])
        eq_(cn.type, amo.CONTRIB_PENDING)
        eq_(cn.user, self.user)
        eq_(cn.price_tier, self.price)
        eq_(data['bluevia_jwt'], bluevia_jwt)

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


@mock.patch.object(settings, 'SECLUSION_HOSTS', ['host'])
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

    def post(self):
        return self.client.post(reverse('bluevia.postback'),
                                data=self.jwt(), content_type='text/plain')

    def jwt_dict(self, expiry=3600):
        issued_at = calendar.timegm(time.gmtime())
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
                    'productData': 'contrib_uuid=%s' % self.contrib.uuid
                },
                'response': {
                    'transactionID': '<BlueVia-trans-id>'
                }}

    def jwt(self, **kw):
        return jwt.encode(self.jwt_dict(**kw), self.bluevia_dev_secret)

    @fudge.patch('lib.pay_server.base.requests.post')
    def test_valid(self, api_post):
        api_post.expects_call().returns(Mock(status_code=200,
                                             text='{"valid": true}'))
        resp = self.post()
        eq_(resp.status_code, 200)
        eq_(resp.content, '<BlueVia-trans-id>')
        cn = Contribution.objects.get(pk=self.contrib.pk)
        eq_(cn.type, amo.CONTRIB_PURCHASE)

    @fudge.patch('lib.pay_server.base.requests.post')
    def test_invalid(self, api_post):
        api_post.expects_call().returns(Mock(status_code=200,
                                             text='{"valid": false}'))
        resp = self.post()
        eq_(resp.status_code, 400)
        cn = Contribution.objects.get(pk=self.contrib.pk)
        eq_(cn.type, amo.CONTRIB_PENDING)
