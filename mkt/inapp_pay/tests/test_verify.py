import calendar
from datetime import datetime, timedelta
import json
import time

from django.conf import settings

import mock
from nose.tools import eq_, raises

import amo

from mkt.inapp_pay.tests.test_views import PaymentTest
from mkt.inapp_pay.verify import (verify_request, UnknownAppError,
                                 RequestVerificationError, RequestExpired,
                                 AppPaymentsDisabled, AppPaymentsRevoked,
                                 InvalidRequest)


class TestVerify(PaymentTest):

    def test_ok(self):
        payload = self.payload()
        data = verify_request(self.request(payload=json.dumps(payload)))
        for k, v in payload.items():
            eq_(data[k], payload[k],
                'key %r did not match: source: %r != decoded: %r'
                % (k, data[k], payload[k]))

    @raises(UnknownAppError)
    def test_unknown_app(self):
        verify_request(self.request(app_id='unknown'))

    @raises(RequestVerificationError)
    def test_unknown_secret(self):
        verify_request(self.request(app_secret='invalid'))

    @raises(RequestVerificationError)
    def test_garbage_request(self):
        verify_request('<not valid JWT>')

    @raises(RequestVerificationError)
    def test_non_ascii_jwt(self):
        verify_request(u'Ivan Krsti\u0107 is in your JWT')

    @raises(RequestVerificationError)
    def test_mangled_json(self):
        encoded = self.request(payload='[\\}()')  # json syntax error
        verify_request(encoded)

    @raises(RequestExpired)
    def test_expired(self):
        now = calendar.timegm(time.gmtime())
        old = datetime.utcfromtimestamp(now) - timedelta(minutes=1)
        exp = calendar.timegm(old.timetuple())
        verify_request(self.request(exp=exp))

    @raises(RequestExpired)
    def test_expired_iat(self):
        old = calendar.timegm(time.gmtime()) - 3660  # 1hr, 1min ago
        verify_request(self.request(iat=old))

    @raises(RequestVerificationError)
    def test_invalid_expiry(self):
        verify_request(self.request(exp='<not a number>'))

    @raises(RequestVerificationError)
    def test_invalid_expiry_non_ascii(self):
        payload = self.payload()
        payload['exp'] = u'Ivan Krsti\u0107 is in your JWT'
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(RequestVerificationError)
    def test_none_expiry(self):
        payload = self.payload()
        payload['exp'] = None
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(RequestVerificationError)
    def test_invalid_iat_non_ascii(self):
        payload = self.payload()
        payload['iat'] = u'Ivan Krsti\u0107 is in your JWT'
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(RequestVerificationError)
    def test_none_iat(self):
        payload = self.payload()
        payload['iat'] = None
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(AppPaymentsRevoked)
    def test_revoked(self):
        self.inapp_config.update(status=amo.INAPP_STATUS_REVOKED)
        verify_request(self.request())

    @raises(AppPaymentsDisabled)
    def test_inactive(self):
        self.inapp_config.update(status=amo.INAPP_STATUS_INACTIVE)
        verify_request(self.request())

    @raises(InvalidRequest)
    def test_not_before(self):
        payload = self.payload()
        nbf = calendar.timegm(time.gmtime()) + 310  # 5:10 in the future
        payload['nbf'] = nbf
        verify_request(self.request(payload=json.dumps(payload)))

    def test_ignore_invalid_nbf(self):
        payload = self.payload()
        payload['nbf'] = '<garbage>'
        data = verify_request(self.request(payload=json.dumps(payload)))
        eq_(data['nbf'], None)

    @raises(InvalidRequest)
    def test_require_price(self):
        payload = self.payload()
        del payload['request']['price']
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(InvalidRequest)
    def test_require_currency(self):
        payload = self.payload()
        del payload['request']['currency']
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(InvalidRequest)
    def test_require_name(self):
        payload = self.payload()
        del payload['request']['name']
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(InvalidRequest)
    def test_require_description(self):
        payload = self.payload()
        del payload['request']['description']
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(InvalidRequest)
    def test_require_request(self):
        payload = self.payload()
        del payload['request']
        verify_request(self.request(payload=json.dumps(payload)))

    @mock.patch.object(settings, 'INAPP_PAYMENT_AUD', 'foobar')
    def test_audience_is_settable(self):
        payload = self.payload()
        payload['aud'] = 'foobar'
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(InvalidRequest)
    def test_invalid_audience(self):
        payload = self.payload()
        payload['aud'] = 'foobar'
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(InvalidRequest)
    def test_missing_audience(self):
        payload = self.payload()
        del payload['aud']
        verify_request(self.request(payload=json.dumps(payload)))

    @raises(RequestVerificationError)
    def test_malformed_jwt(self):
        verify_request(self.request() + 'x')
