import calendar
import json
import jwt
import time

from django.conf import settings

from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle.models

from addons.models import Addon
import amo.tests
from amo.urlresolvers import reverse

from mkt.payments.models import InappConfig, InappPayLog


class PaymentTest(amo.tests.TestCase):
    fixtures = ['base/337141-steamcube', 'base/users']

    def setUp(self):
        cfg = self.inapp_config = InappConfig(addon=self.get_app(),
                                              status=amo.INAPP_STATUS_ACTIVE)
        cfg.public_key = self.app_id = InappConfig.generate_public_key()
        cfg.private_key = self.app_secret = InappConfig.generate_private_key()
        cfg.save()

    def get_app(self):
        return Addon.objects.get(pk=337141)

    def payload(self, app_id=None, exp=None, iat=None):
        if not app_id:
            app_id = self.app_id
        if not iat:
            iat = calendar.timegm(time.gmtime())
        if not exp:
            exp = iat + 3600  # expires in 1 hour
        return {
            'iss': app_id,
            'aud': settings.INAPP_PAYMENT_AUD,
            'typ': 'mozilla/payments/pay/v1',
            'exp': exp,
            'iat': iat,
            'request': {
                'price': '0.99',
                'currency': 'USD',
                'name': 'My bands latest album',
                'description': '320kbps MP3 download, DRM free!',
                'productdata': 'my_product_id=1234'
            }
        }

    def request(self, app_secret=None, payload=None, **payload_kw):
        if not app_secret:
            app_secret = self.app_secret
        if not payload:
            payload = json.dumps(self.payload(**payload_kw))
        encoded = jwt.encode(payload, app_secret, algorithm='HS256')
        return unicode(encoded)  # django always passes unicode


class TestPay(PaymentTest):

    def setUp(self):
        super(TestPay, self).setUp()
        waffle.models.Switch.objects.create(name='in-app-payments-ui',
                                            active=True)
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def test_missing_pay_request_on_start(self):
        rp = self.client.get(reverse('payments.pay_start'))
        eq_(rp.status_code, 400)

    def test_missing_pay_request(self):
        rp = self.client.post(reverse('payments.pay'))
        eq_(rp.status_code, 400)

    def test_pay_start(self):
        payload = self.payload()
        req = self.request(payload=json.dumps(payload))
        rp = self.client.get(reverse('payments.pay_start'),
                             data=dict(req=req))
        eq_(rp.status_code, 200)
        doc = pq(rp.content)
        eq_(doc('.paypal-content h5').text(), payload['request']['name'])
        eq_(doc('.paypal-content .price').text(), 'USD 0.99')
        # TODO(Kumar) UI is still in the works here.

        log = InappPayLog.objects.get()
        eq_(log.action, InappPayLog._actions['PAY_START'])
        eq_(log.config.pk, self.inapp_config.pk)
        assert log.session_key, 'Unexpected session_key: %r' % log.session_key

    def test_pay_start_error(self):
        rp = self.client.get(reverse('payments.pay_start'),
                             data=dict(req=self.request(app_secret='invalid')))
        eq_(rp.status_code, 200)
        doc = pq(rp.content)
        eq_(doc('h3').text(), 'Payment Error')

        log = InappPayLog.objects.get()
        eq_(log.action, InappPayLog._actions['EXCEPTION'])
        eq_(log.app_public_key, self.inapp_config.public_key)
        eq_(log.exception, InappPayLog._exceptions['RequestVerificationError'])
        assert log.session_key, 'Unexpected session_key: %r' % log.session_key

    def test_pay_error(self):
        rp = self.client.post(reverse('payments.pay'),
                              data=dict(req=self.request(app_id='unknown')))
        eq_(rp.status_code, 200)
        doc = pq(rp.content)
        eq_(doc('h3').text(), 'Payment Error')
