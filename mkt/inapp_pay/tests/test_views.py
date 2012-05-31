# -*- coding: utf-8 -*-
import calendar
from decimal import Decimal
import json
import jwt
import time

from django.conf import settings

import fudge
from fudge.inspector import arg
import mock
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle.models

from addons.models import Addon
import amo
import amo.tests
from amo.urlresolvers import reverse
from market.models import PreApprovalUser
from paypal import PaypalError
from stats.models import Contribution
from users.models import UserProfile

from mkt.inapp_pay.models import (InappPayment, InappConfig, InappPayLog,
                                  InappImage)


class InappPaymentUtil:

    def make_contrib(self, **contrib_kw):
        payload = self.payload()
        uuid_ = '12345'
        kw = dict(addon_id=self.app.pk, amount=payload['request']['price'],
                  source='', source_locale='en-US',
                  currency=payload['request']['currency'],
                  uuid=uuid_, type=amo.CONTRIB_INAPP_PENDING,
                  paykey='some-paykey', user=self.user)
        kw.update(contrib_kw)
        return Contribution.objects.create(**kw)

    def make_payment(self, contrib=None):
        app_payment = self.payload()
        if not contrib:
            contrib = self.make_contrib()
        return InappPayment.objects.create(
                            config=self.inapp_config,
                            contribution=contrib,
                            name=app_payment['request']['name'],
                            description=app_payment['request']['description'],
                            app_data=app_payment['request']['productdata'])

    def payload(self, app_id=None, exp=None, iat=None,
                typ='mozilla/payments/pay/v1', extra=None):
        if not app_id:
            app_id = self.app_id
        if not iat:
            iat = calendar.timegm(time.gmtime())
        if not exp:
            exp = iat + 3600  # expires in 1 hour
        req = {'price': '0.99',
               'currency': 'USD',
               'name': 'My bands latest album',
               'description': '320kbps MP3 download, DRM free!',
               'productdata': 'my_product_id=1234'}
        if extra:
            req.update(extra)
        return {
            'iss': app_id,
            'aud': settings.INAPP_MARKET_ID,
            'typ': typ,
            'exp': exp,
            'iat': iat,
            'request': req
        }


@mock.patch.object(settings, 'DEBUG', True)
class PaymentTest(InappPaymentUtil, amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube', 'base/users']

    @mock.patch.object(settings, 'DEBUG', True)
    def setUp(self):
        self.app = self.get_app()
        cfg = self.inapp_config = InappConfig(addon=self.app,
                                              status=amo.INAPP_STATUS_ACTIVE)
        cfg.public_key = self.app_id = InappConfig.generate_public_key()
        self.app_secret = InappConfig.generate_private_key()
        cfg.save()
        cfg.set_private_key(self.app_secret)
        self.app.paypal_id = 'app-dev-paypal@theapp.com'
        self.app.save()

    def get_app(self):
        return Addon.objects.get(pk=337141)

    def request(self, app_secret=None, payload=None, **payload_kw):
        if not app_secret:
            app_secret = self.app_secret
        if not payload:
            payload = json.dumps(self.payload(**payload_kw))
        encoded = jwt.encode(payload, app_secret, algorithm='HS256')
        return unicode(encoded)  # django always passes unicode


class PaymentViewTest(PaymentTest):

    def setUp(self):
        super(PaymentViewTest, self).setUp()
        waffle.models.Switch.objects.create(name='in-app-payments-ui',
                                            active=True)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')


@mock.patch.object(settings, 'DEBUG', True)
class PayFlowTest(PaymentViewTest):

    def setUp(self):
        super(PayFlowTest, self).setUp()
        PreApprovalUser.objects.create(user=self.user,
                                       paypal_key='fantasmic')

    def start(self, req=None, extra_request=None):
        if not req:
            payload = self.payload()
            if extra_request:
                payload['request'].update(extra_request)
            req = self.request(payload=json.dumps(payload))
        return self.client.get(reverse('inapp_pay.pay_start'),
                               data=dict(req=req))


@mock.patch.object(settings, 'DEBUG', True)
@mock.patch('mkt.inapp_pay.tasks.fetch_product_image')
class TestPayStart(PayFlowTest):

    def test_missing_pay_request_on_start(self, fetch_prod_im):
        rp = self.client.get(reverse('inapp_pay.pay_start'))
        eq_(rp.status_code, 400)

    def test_pay_start(self, fetch_prod_im):
        rp = self.start()
        eq_(rp.status_code, 200)
        assert 'x-frame-options' not in rp, "Can't deny with x-frame-options"
        self.assertTemplateUsed(rp, 'inapp_pay/pay_start.html')

        log = InappPayLog.objects.get()
        eq_(log.action, InappPayLog._actions['PAY_START'])
        eq_(log.config.pk, self.inapp_config.pk)
        assert log.session_key, 'Unexpected session_key: %r' % log.session_key
        assert fetch_prod_im.delay.called, 'product image fetched'

    def test_not_logged_in(self, fetch_prod_im):
        self.client.logout()
        rp = self.start()
        eq_(rp.status_code, 200)
        self.assertTemplateUsed(rp, 'inapp_pay/login.html')

    def test_no_preapproval(self, fetch_prod_im):
        self.user.preapprovaluser.delete()
        rp = self.start()
        eq_(rp.status_code, 200)
        self.assertTemplateUsed(rp, 'inapp_pay/nowallet.html')

    def test_empty_preapproval(self, fetch_prod_im):
        self.user.preapprovaluser.update(paypal_key='')
        rp = self.start()
        eq_(rp.status_code, 200)
        self.assertTemplateUsed(rp, 'inapp_pay/nowallet.html')

    def test_pay_start_error(self, fetch_prod_im):
        self.inapp_config.addon.support_url = 'http://friendlyapp.org/support'
        self.inapp_config.addon.support_email = 'help@friendlyapp.org'
        self.inapp_config.addon.save()
        rp = self.start(req=self.request(app_secret='invalid'))
        eq_(rp.status_code, 200)
        doc = pq(rp.content)
        eq_(doc('h3').text(), 'Payment Error')
        self.assertContains(rp, 'mailto:help@friendlyapp.org')
        self.assertContains(rp, 'friendlyapp.org/support')

        log = InappPayLog.objects.get()
        eq_(log.action, InappPayLog._actions['EXCEPTION'])
        eq_(log.app_public_key, self.inapp_config.public_key)
        eq_(log.exception, InappPayLog._exceptions['RequestVerificationError'])
        assert log.session_key, 'Unexpected session_key: %r' % log.session_key
        assert not fetch_prod_im.delay.called, (
                    'product image not fetched on error')

    def test_pay_error_no_app_id(self, fetch_prod_im):
        self.inapp_config.addon.support_url = 'http://friendlyapp.org/support'
        self.inapp_config.addon.support_email = 'help@friendlyapp.org'
        self.inapp_config.addon.save()
        rp = self.start(req='<garbage>')
        eq_(rp.status_code, 200)
        self.assertNotContains(rp, 'mailto:help@friendlyapp.org')
        self.assertNotContains(rp, 'friendlyapp.org/support')

    def test_pay_error_no_support(self, fetch_prod_im):
        self.inapp_config.addon.support_url = None
        self.inapp_config.addon.support_email = None
        self.inapp_config.addon.save()
        rp = self.start(req=self.request(app_secret='invalid'))
        eq_(rp.status_code, 200)
        self.assertNotContains(rp, 'mailto:help@friendlyapp.org')
        self.assertNotContains(rp, 'friendlyapp.org/support')

    @mock.patch.object(settings, 'INAPP_VERBOSE_ERRORS', True)
    def test_verbose_error(self, fetch_prod_im):
        rp = self.start(req=self.request(app_secret='invalid'))
        eq_(rp.status_code, 200)
        self.assertContains(rp, 'RequestVerificationError')


@mock.patch.object(settings, 'DEBUG', True)
class TestPay(PaymentViewTest):

    def setUp(self):
        super(TestPay, self).setUp()
        self.complete_url = reverse('inapp_pay.pay_status',
                                    args=[self.inapp_config.pk, 'complete'])
        self.cancel_url = reverse('inapp_pay.pay_status',
                                  args=[self.inapp_config.pk, 'cancel'])
        self.netreq = mock.patch('mkt.inapp_pay.tasks.requests')
        self.netreq.start()

    def tearDown(self):
        super(TestPay, self).tearDown()
        self.netreq.stop()

    def assert_payment_done(self, payload, contrib_type):
        cnt = Contribution.objects.get(addon=self.app)
        eq_(cnt.addon.pk, self.app.pk)
        eq_(cnt.type, contrib_type)
        eq_(cnt.amount, Decimal(payload['request']['price']))
        eq_(cnt.currency, payload['request']['currency'])

        pmt = InappPayment.objects.get(contribution=cnt)
        eq_(pmt.config, self.inapp_config)
        eq_(pmt.name, payload['request']['name'])
        eq_(pmt.description, payload['request']['description'])
        eq_(pmt.app_data, payload['request']['productdata'])

    def test_missing_pay_request(self):
        rp = self.client.post(reverse('inapp_pay.pay'))
        eq_(rp.status_code, 400)

    def test_invalid_pay_request(self):
        rp = self.client.post(reverse('inapp_pay.pay'),
                              data=dict(req=self.request(app_id='unknown')))
        eq_(rp.status_code, 200)
        doc = pq(rp.content)
        eq_(doc('h3').text(), 'Payment Error')

    @fudge.patch('paypal.get_paykey')
    def test_paykey_exception(self, get_paykey):
        get_paykey.expects_call().raises(PaypalError())
        res = self.client.post(reverse('inapp_pay.pay'),
                               data=dict(req=self.request()))
        self.assertContains(res, 'Payment Error')
        eq_(InappPayLog.objects.get().action,
            InappPayLog._actions['PAY_ERROR'])

    @mock.patch.object(settings, 'INAPP_VERBOSE_ERRORS', True)
    @fudge.patch('paypal.get_paykey')
    def test_verbose_paypal_error(self, get_paykey):
        get_paykey.expects_call().raises(PaypalError())
        res = self.client.post(reverse('inapp_pay.pay'),
                               data=dict(req=self.request()))
        self.assertContains(res, 'PaypalError')

    @fudge.patch('paypal.get_paykey')
    def test_no_preauth(self, get_paykey):
        payload = self.payload()
        (get_paykey.expects_call()
                   .with_matching_args(addon_id=self.app.pk,
                                       amount=payload['request']['price'],
                                       currency=payload['request']['currency'],
                                       email=self.app.paypal_id)
                   .returns(['some-pay-key', '']))
        req = self.request(payload=json.dumps(payload))
        res = self.client.post(reverse('inapp_pay.pay'), dict(req=req))
        assert 'some-pay-key' in res['Location'], (
                                'Unexpected redirect: %s' % res['Location'])

        log = InappPayLog.objects.get()
        eq_(log.action, InappPayLog._actions['PAY'])
        eq_(log.config.pk, self.inapp_config.pk)

        self.assert_payment_done(payload, amo.CONTRIB_INAPP_PENDING)

    @fudge.patch('paypal.check_purchase')
    @fudge.patch('paypal.get_paykey')
    @fudge.patch('mkt.inapp_pay.tasks.payment_notify')
    def test_preauth_ok(self, check_purchase, get_paykey, payment_notify):
        payload = self.payload()

        get_paykey.expects_call().returns(['some-pay-key', 'COMPLETED'])
        check_purchase.expects_call().returns('COMPLETED')
        payment_notify.expects('delay').with_args(arg.any())  # pay ID to-be

        req = self.request(payload=json.dumps(payload))
        self.client.post(reverse('inapp_pay.pay'), dict(req=req))

        logs = InappPayLog.objects.all().order_by('created')
        eq_(logs[0].action, InappPayLog._actions['PAY'])
        eq_(logs[1].action, InappPayLog._actions['PAY_COMPLETE'])

    @fudge.patch('paypal.check_purchase')
    @fudge.patch('paypal.get_paykey')
    def test_unverified_preauth(self, check_purchase, get_paykey):
        get_paykey.expects_call().returns(['some-pay-key', 'COMPLETED'])
        check_purchase.expects_call().returns('')  # unverified preauth
        res = self.client.post(reverse('inapp_pay.pay'),
                               dict(req=self.request()))
        assert 'some-pay-key' in res['Location'], (
                                'Unexpected redirect: %s' % res['Location'])
        eq_(Contribution.objects.get().type, amo.CONTRIB_INAPP_PENDING)

    @fudge.patch('mkt.inapp_pay.tasks.payment_notify')
    def test_pay_complete(self, notify_app):
        cnt = self.make_contrib()
        payment = self.make_payment(contrib=cnt)
        notify_app.expects('delay').with_args(payment.pk)
        res = self.client.get(self.complete_url, {'uuid': cnt.uuid})
        eq_(res.status_code, 200)
        #self.assertContains(res, 'Payment received')
        cnt = Contribution.objects.get(pk=cnt.pk)
        eq_(cnt.type, amo.CONTRIB_INAPP)
        eq_(InappPayLog.objects.get().action,
            InappPayLog._actions['PAY_COMPLETE'])

    def test_invalid_contrib_uuid(self):
        res = self.client.get(self.complete_url, {'uuid': 'invalid-uuid'})
        self.assertContains(res, 'Payment Error')

    def test_non_ascii_invalid_uuid(self):
        res = self.client.get(self.complete_url, {'uuid': u'Азәрбајҹан'})
        self.assertContains(res, 'Payment Error')

    def test_missing_uuid(self):
        res = self.client.get(self.complete_url)
        self.assertContains(res, 'Payment Error')


@mock.patch.object(settings, 'DEBUG', True)
@mock.patch('mkt.inapp_pay.tasks.fetch_product_image')
class TestProductImage(PayFlowTest):

    def setUp(self):
        super(TestProductImage, self).setUp()
        self.image_url = '/my/image.jpg'
        InappImage.objects.create(config=self.inapp_config,
                                  image_url=self.image_url,
                                  valid=True)

    def start(self, req=None, extra_request=None):
        if not extra_request:
            extra_request = {'imageURL': self.image_url}
        return super(TestProductImage, self).start(req=req,
                                                   extra_request=extra_request)

    def test_show_image(self, fetch_image):
        resp = self.start()
        doc = pq(resp.content)
        eq_(doc('.product-details img').attr('src'),
            self.inapp_config.image_url(self.image_url))

    def test_show_default(self, fetch_image):
        InappImage.objects.all().delete()
        resp = self.start()
        doc = pq(resp.content)
        eq_(doc('.product-details img').attr('src'),
            InappImage.default_image_url())

    def test_handle_multiple(self, fetch_image):
        InappImage.objects.create(config=self.inapp_config,
                                  image_url='/some/other.jpg',
                                  valid=True)
        resp = self.start()
        doc = pq(resp.content)
        eq_(doc('.product-details img').attr('src'),
            self.inapp_config.image_url(self.image_url))
