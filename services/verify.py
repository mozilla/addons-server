import calendar
from datetime import datetime
from email.Utils import formatdate
import json
import re
from time import gmtime, time
from urlparse import parse_qsl

from django.core.management import setup_environ

from utils import (log_configure, log_exception, log_info, mypool,
                   ADDON_PREMIUM, CONTRIB_CHARGEBACK,
                   CONTRIB_PURCHASE, CONTRIB_REFUND)

# This has to be _mkt to get SIGNING_SERVER_ACTIVE
try:
    import settings_local_mkt as settings
except:
    # Fallback for jenkins.
    import settings_local as settings

setup_environ(settings)

# Go configure the log.
log_configure()

from browserid.errors import ExpiredSignatureError
import jwt
from lib.crypto.receipt import sign
from lib.cef_loggers import receipt_cef

# This has to be imported after the settings (utils).
import receipts  # used for patching in the tests
from receipts import certs
from statsd import statsd


class VerificationError(Exception):
    pass


class Verify:

    def __init__(self, addon_id, receipt, environ):
        # The regex should ensure that only sane ints get to this point.
        self.addon_id = int(addon_id)
        self.receipt = receipt
        self.environ = environ
        # These will be extracted from the receipt.
        self.user_id = None
        self.premium = None
        # This is so the unit tests can override the connection.
        self.conn, self.cursor = None, None

    def __call__(self, check_purchase=True):
        if not self.cursor:
            self.conn = mypool.connect()
            self.cursor = self.conn.cursor()

        # Try and decode the receipt data.
        # If its invalid, then just return invalid rather than give out any
        # information.
        try:
            receipt = decode_receipt(self.receipt)
        except:
            log_exception({'receipt': '%s...' % self.receipt[:10],
                           'addon': self.addon_id})
            self.log('Error decoding receipt')
            return self.invalid()

        try:
            assert receipt['user']['type'] == 'directed-identifier'
        except (AssertionError, KeyError):
            self.log('No directed-identifier supplied')
            return self.invalid()

        # Get the addon and user information from the installed table.
        try:
            uuid = receipt['user']['value']
        except KeyError:
            # If somehow we got a valid receipt without a uuid
            # that's a problem. Log here.
            self.log('No user in receipt')
            return self.invalid()

        # Newer receipts have the addon_id in the storedata,
        # if it doesn't match the URL, then it's wrong.
        receipt_addon_id = None
        try:
            storedata = receipt['product']['storedata']
            receipt_addon_id = int(dict(parse_qsl(storedata)).get('id', ''))
        except:
            # There was some value for storedata but it was invalid.
            self.log('Invalid store data')
            return self.invalid()

        # The addon_id in the URL and the receipt did not match, fail.
        if receipt_addon_id and receipt_addon_id != self.addon_id:
            self.log('The addon_id in the receipt and the URL did not match.')
            return self.invalid()

        sql = """SELECT id, user_id, premium_type FROM users_install
                 WHERE addon_id = %(addon_id)s
                 AND uuid = %(uuid)s LIMIT 1;"""
        self.cursor.execute(sql, {'addon_id': self.addon_id,
                                  'uuid': uuid})
        result = self.cursor.fetchone()
        if not result:
            # We've got no record of this receipt being created.
            self.log('No entry in users_install for uuid: %s' % uuid)
            return self.invalid()

        rid, self.user_id, self.premium = result

        # If it's a premium addon, then we need to get that the purchase
        # information.
        if self.premium != ADDON_PREMIUM:
            self.log('Valid receipt, not premium')
            return self.ok_or_expired(receipt)

        elif self.premium and not check_purchase:
            return self.ok_or_expired(receipt)

        else:
            sql = """SELECT id, type FROM addon_purchase
                     WHERE addon_id = %(addon_id)s
                     AND user_id = %(user_id)s LIMIT 1;"""
            self.cursor.execute(sql, {'addon_id': self.addon_id,
                                      'user_id': self.user_id})
            result = self.cursor.fetchone()
            if not result:
                self.log('Invalid receipt, no purchase')
                return self.invalid()

            if result[-1] in [CONTRIB_REFUND, CONTRIB_CHARGEBACK]:
                self.log('Valid receipt, but refunded')
                return self.refund()

            elif result[-1] == CONTRIB_PURCHASE:
                self.log('Valid receipt')
                return self.ok_or_expired(receipt)

            else:
                self.log('Valid receipt, but invalid contribution')
                return self.invalid()

    def format_date(self, secs):
        return '%s GMT' % formatdate(time() + secs)[:25]

    def get_headers(self, length):
        return [('Access-Control-Allow-Origin', '*'),
                ('Access-Control-Allow-Methods', 'POST'),
                ('Content-Type', 'application/json'),
                ('Content-Length', str(length)),
                ('Cache-Control', 'no-cache'),
                ('Last-Modified', self.format_date(0))]

    def invalid(self):
        return json.dumps({'status': 'invalid'})

    def log(self, msg):
        log_info({'receipt': '%s...' % self.receipt[:10],
                  'addon': self.addon_id}, msg)

    def ok_or_expired(self, receipt):
        # This receipt is ok now let's check it's expiry.
        # If it's expired, we'll have to return a new receipt
        try:
            expire = int(receipt.get('exp', 0))
        except ValueError:
            self.log('Error with expiry in the receipt')
            return self.expired(receipt)

        now = calendar.timegm(gmtime()) + 10  # For any clock skew.
        if now > expire:
            self.log('This receipt has expired: %s UTC < %s UTC'
                                 % (datetime.utcfromtimestamp(expire),
                                    datetime.utcfromtimestamp(now)))
            return self.expired(receipt)

        return self.ok()

    def ok(self):
        return json.dumps({'status': 'ok'})

    def refund(self):
        return json.dumps({'status': 'refunded'})

    def expired(self, receipt):
        if settings.WEBAPPS_RECEIPT_EXPIRED_SEND:
            receipt['exp'] = (calendar.timegm(gmtime()) +
                              settings.WEBAPPS_RECEIPT_EXPIRY_SECONDS)
            receipt_cef.log(self.environ, self.addon_id, 'sign',
                            'Expired signing request')
            return json.dumps({'status': 'expired', 'receipt': sign(receipt)})
        return json.dumps({'status': 'expired'})


def decode_receipt(receipt):
    """
    Cracks the receipt using the private key. This will probably change
    to using the cert at some point, especially when we get the HSM.
    """
    with statsd.timer('services.decode'):
        if settings.SIGNING_SERVER_ACTIVE:
            verifier = certs.ReceiptVerifier()
            try:
                result = verifier.verify(receipt)
            except ExpiredSignatureError:
                # Until we can do something meaningful with this, just ignore.
                return jwt.decode(receipt.split('~')[1], verify=False)
            if not result:
                raise VerificationError()
            return jwt.decode(receipt.split('~')[1], verify=False)
        else:
            key = jwt.rsa_load(settings.WEBAPPS_RECEIPT_KEY)
            raw = jwt.decode(receipt, key)
    return raw


# For consistency with the rest of amo, we'll include addon id in the
# URL and pull it out using this regex.
id_re = re.compile('/verify/(?P<addon_id>\d+)$')


def application(environ, start_response):
    status = '200 OK'
    with statsd.timer('services.verify'):

        data = environ['wsgi.input'].read()
        try:
            addon_id = id_re.search(environ['PATH_INFO']).group('addon_id')
        except AttributeError:
            output = ''
            log_info({'receipt': '%s...' % data[:10], 'addon': 'empty'},
                     'Wrong url %s' % environ['PATH_INFO'][:20])
            start_response('500 Internal Server Error', [])
            return [output]

        try:
            verify = Verify(addon_id, data, environ)
            output = verify()
            start_response(status, verify.get_headers(len(output)))
            receipt_cef.log(environ, addon_id, 'verify',
                            'Receipt verification')
        except:
            output = ''
            log_exception({'receipt': '%s...' % data[:10], 'addon': addon_id})
            receipt_cef.log(environ, addon_id, 'verify',
                            'Receipt verification error')
            start_response('500 Internal Server Error', [])

    return [output]
