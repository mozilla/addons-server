import calendar
from datetime import datetime, timedelta
import json
import time

from django.conf import settings

import mock
from nose.tools import eq_, raises

import amo

from mkt.inapp_pay.models import InappPayment
from mkt.inapp_pay.tests.test_views import PaymentTest
from mkt.inapp_pay.verify import (verify_request, UnknownAppError,
                                  RequestVerificationError, RequestExpired,
                                  AppPaymentsDisabled, AppPaymentsRevoked,
                                  InvalidRequest)


@mock.patch.object(settings, 'DEBUG', True)
class TestVerify(PaymentTest):

    def verify(self, request=None, update=None, update_request=None):
        if not request:
            payload = self.payload()
            if update_request:
                payload['request'].update(update_request)
            if update:
                payload.update(update)
            request = self.request(payload=json.dumps(payload))
        return verify_request(request)

    def test_ok(self):
        payload = self.payload()
        data = verify_request(self.request(payload=json.dumps(payload)))
        for k, v in payload.items():
            eq_(data[k], payload[k],
                'key %r did not match: source: %r != decoded: %r'
                % (k, data[k], payload[k]))

    @raises(UnknownAppError)
    def test_unknown_app(self):
        self.verify(self.request(app_id='unknown'))

    @raises(RequestVerificationError)
    def test_unknown_secret(self):
        self.verify(self.request(app_secret='invalid'))

    @raises(RequestVerificationError)
    def test_garbage_request(self):
        self.verify('<not valid JWT>')

    @raises(RequestVerificationError)
    def test_non_ascii_jwt(self):
        self.verify(u'Ivan Krsti\u0107 is in your JWT')

    @raises(RequestVerificationError)
    def test_mangled_json(self):
        encoded = self.request(payload='[\\}()')  # json syntax error
        self.verify(encoded)

    @raises(RequestExpired)
    def test_expired(self):
        now = calendar.timegm(time.gmtime())
        old = datetime.utcfromtimestamp(now) - timedelta(minutes=1)
        exp = calendar.timegm(old.timetuple())
        self.verify(self.request(exp=exp))

    @raises(RequestExpired)
    def test_expired_iat(self):
        old = calendar.timegm(time.gmtime()) - 3660  # 1hr, 1min ago
        self.verify(self.request(iat=old))

    @raises(RequestVerificationError)
    def test_invalid_expiry(self):
        self.verify(self.request(exp='<not a number>'))

    @raises(RequestVerificationError)
    def test_invalid_expiry_non_ascii(self):
        self.verify(update={'exp': u'Ivan Krsti\u0107 is in your JWT'})

    @raises(RequestVerificationError)
    def test_none_expiry(self):
        self.verify(update={'exp': None})

    @raises(RequestVerificationError)
    def test_invalid_iat_non_ascii(self):
        self.verify(update={'iat': u'Ivan Krsti\u0107 is in your JWT'})

    @raises(RequestVerificationError)
    def test_none_iat(self):
        self.verify(update={'iat': None})

    @raises(AppPaymentsRevoked)
    def test_revoked(self):
        self.inapp_config.update(status=amo.INAPP_STATUS_REVOKED)
        self.verify()

    @raises(AppPaymentsDisabled)
    def test_inactive(self):
        self.inapp_config.update(status=amo.INAPP_STATUS_INACTIVE)
        self.verify()

    @raises(InvalidRequest)
    def test_not_before(self):
        nbf = calendar.timegm(time.gmtime()) + 310  # 5:10 in the future
        self.verify(update={'nbf': nbf})

    def test_ignore_invalid_nbf(self):
        data = self.verify(update={'nbf': '<garbage>'})
        eq_(data['nbf'], None)

    @raises(InvalidRequest)
    def test_require_name(self):
        payload = self.payload()
        del payload['request']['name']
        self.verify(self.request(payload=json.dumps(payload)))

    @raises(InvalidRequest)
    def test_require_description(self):
        payload = self.payload()
        del payload['request']['description']
        self.verify(self.request(payload=json.dumps(payload)))

    @raises(InvalidRequest)
    def test_require_request(self):
        payload = self.payload()
        del payload['request']
        self.verify(self.request(payload=json.dumps(payload)))

    @mock.patch.object(settings, 'INAPP_MARKET_ID', 'appsafterdark.com')
    def test_audience_is_settable(self):
        self.verify(update={'aud': 'appsafterdark.com'})

    @raises(InvalidRequest)
    def test_invalid_audience(self):
        self.verify(update={'aud': 'appsafterdark.com'})

    @raises(InvalidRequest)
    def test_missing_audience(self):
        payload = self.payload()
        del payload['aud']
        self.verify(self.request(payload=json.dumps(payload)))

    @raises(RequestVerificationError)
    def test_malformed_jwt(self):
        self.verify(self.request() + 'x')

    @raises(InvalidRequest)
    def test_empty_name(self):
        self.verify(update_request={'name': ''})

    @raises(InvalidRequest)
    def test_name_too_long(self):
        max = InappPayment._meta.get_field_by_name('name')[0].max_length
        self.verify(update_request={'name': 'x' * (max + 1)})

    @raises(InvalidRequest)
    def test_description_too_long(self):
        max = InappPayment._meta.get_field_by_name('description')[0].max_length
        self.verify(update_request={'description': 'x' * (max + 1)})

    @raises(InvalidRequest)
    def test_app_data_too_long(self):
        max = InappPayment._meta.get_field_by_name('app_data')[0].max_length
        self.verify(update_request={'productdata': 'x' * (max + 1)})

    @raises(UnknownAppError)
    def test_non_public_app(self):
        self.app.update(status=amo.STATUS_PENDING)
        self.verify()

    @raises(InvalidRequest)
    def test_require_price_tier(self):
        payload = self.payload()
        del payload['request']['priceTier']
        self.verify(self.request(payload=json.dumps(payload)))

    @raises(InvalidRequest)
    def test_unknown_price_tier(self):
        self.verify(update_request={'priceTier': 9999})

    @raises(InvalidRequest)
    def test_malformed_price_tier(self):
        self.verify(update_request={'priceTier': '<garbage>'})
