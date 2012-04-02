import calendar
import httplib
import socket
import time
import urllib2

from django.conf import settings

import fudge
from fudge.inspector import arg
import jwt
from nose.tools import eq_

import amo
from users.models import UserProfile

from mkt.inapp_pay import tasks
from mkt.inapp_pay.models import InappPayNotice
from mkt.inapp_pay.tests.test_views import PaymentTest


class TestNotifyApp(PaymentTest):

    def setUp(self):
        super(TestNotifyApp, self).setUp()
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.contrib = self.make_contrib()
        self.postback = '/postback'
        self.chargeback = '/chargeback'
        self.domain = 'somenonexistantappdomain.com'
        self.app.update(app_domain=self.domain)
        self.inapp_config.update(postback_url=self.postback,
                                 chargeback_url=self.chargeback)
        self.payment = self.make_payment(contrib=self.contrib)

    def url(self, path):
        # TODO(Kumar) make http(s) configurable. See bug 741484.
        return 'http://' + self.domain + path

    def notify(self):
        tasks.notify_app(amo.INAPP_NOTICE_PAY, self.payment.pk)

    @fudge.patch('mkt.inapp_pay.tasks.urlopen')
    def test_notify_pay(self, urlopen):
        url = self.url(self.postback)
        (urlopen.expects_call().with_args(url, arg.any(),
                                          timeout=5)
                               .returns_fake()
                               .expects('read')
                               .returns(str(self.contrib.pk))
                               .expects('close'))
        self.notify()
        notice = InappPayNotice.objects.get()
        eq_(notice.notice, amo.INAPP_NOTICE_PAY)
        eq_(notice.success, True)
        eq_(notice.url, url)
        eq_(notice.payment.pk, self.payment.pk)

    @fudge.patch('mkt.inapp_pay.tasks.urlopen')
    def test_notify_timeout(self, urlopen):
        reason = socket.timeout('too slow')
        urlopen.expects_call().raises(urllib2.URLError(reason))
        self.notify()
        notice = InappPayNotice.objects.get()
        eq_(notice.success, False)
        eq_(notice.last_error, 'URLError: <urlopen error too slow>')

    @fudge.patch('mkt.inapp_pay.tasks.urlopen')
    def test_http_error(self, urlopen):
        urlopen.expects_call().raises(urllib2.HTTPError('url', 404,
                                                        'Not Found', [], None))
        self.notify()
        notice = InappPayNotice.objects.get()
        eq_(notice.success, False)
        eq_(notice.last_error, 'HTTPError: HTTP Error 404: Not Found')

    @fudge.patch('mkt.inapp_pay.tasks.urlopen')
    def test_invalid_url_error(self, urlopen):
        (urlopen.expects_call()
                .raises(httplib.InvalidURL("nonnumeric port: ''")))
        self.notify()
        notice = InappPayNotice.objects.get()
        eq_(notice.success, False)

    @fudge.patch('mkt.inapp_pay.tasks.urlopen')
    def test_bad_socket(self, urlopen):
        (urlopen.expects_call()
                .returns_fake().expects('read').raises(socket.error))
        self.notify()
        notice = InappPayNotice.objects.get()
        eq_(notice.success, False)

    @fudge.patch('mkt.inapp_pay.tasks.urlopen')
    def test_bad_socket_on_open(self, urlopen):
        urlopen.expects_call().raises(socket.error)
        self.notify()
        notice = InappPayNotice.objects.get()
        eq_(notice.success, False)

    @fudge.patch('mkt.inapp_pay.tasks.urlopen')
    def test_bad_status_line(self, urlopen):
        urlopen.expects_call().raises(httplib.BadStatusLine(None))
        self.notify()
        notice = InappPayNotice.objects.get()
        eq_(notice.success, False)

    @fudge.patch('mkt.inapp_pay.tasks.urlopen')
    def test_invalid_app_response(self, urlopen):
        (urlopen.expects_call().returns_fake()
                               .expects('read')
                               .returns('<not a valid response>')
                               .expects('close'))
        self.notify()
        notice = InappPayNotice.objects.get()
        eq_(notice.success, False)

    @fudge.patch('mkt.inapp_pay.tasks.urlopen')
    def test_signed_app_response(self, urlopen):
        app_payment = self.payload()

        # Ensure that the JWT sent to the app for payment notification
        # includes the same payment data that the app originally sent.
        def is_valid(payload):
            data = jwt.decode(payload, self.inapp_config.private_key,
                              verify=True)
            eq_(data['iss'], settings.INAPP_MARKET_ID)
            eq_(data['aud'], self.inapp_config.public_key)
            eq_(data['typ'], 'mozilla/payments/pay/postback/v1')
            eq_(data['request']['price'], app_payment['request']['price'])
            eq_(data['request']['currency'],
                app_payment['request']['currency'])
            eq_(data['request']['name'], app_payment['request']['name'])
            eq_(data['request']['description'],
                app_payment['request']['description'])
            eq_(data['request']['productdata'],
                app_payment['request']['productdata'])
            eq_(data['response']['transactionID'], self.contrib.pk)
            assert data['iat'] <= calendar.timegm(time.gmtime()) + 60, (
                                'Expected iat to be about now')
            assert data['exp'] > calendar.timegm(time.gmtime()) + 3500, (
                                'Expected exp to be about an hour from now')
            return True

        (urlopen.expects_call().with_args(arg.any(), arg.passes_test(is_valid),
                                          timeout=arg.any())
                               .returns_fake()
                               .expects('read')
                               .returns('<not a valid response>')
                               .expects('close'))
        self.notify()
