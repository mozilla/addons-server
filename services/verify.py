import calendar
from datetime import datetime
import json
from time import gmtime, time
from urlparse import parse_qsl
from wsgiref.handlers import format_date_time

from django.core.management import setup_environ

from utils import (log_configure, log_exception, log_info, mypool,
                   ADDON_PREMIUM, CONTRIB_CHARGEBACK,
                   CONTRIB_PURCHASE, CONTRIB_REFUND)

from services.utils import settings
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
from django_statsd.clients import statsd

status_codes = {
    200: '200 OK',
    405: '405 Method Not Allowed',
    500: '500 Internal Server Error',
}


class VerificationError(Exception):
    pass


class Verify:

    def __init__(self, receipt, environ):
        self.receipt = receipt
        self.environ = environ
        # These will be extracted from the receipt.
        self.addon_id = None
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
            log_info('Error decoding receipt')
            return self.invalid()

        try:
            assert receipt['user']['type'] == 'directed-identifier'
        except (AssertionError, KeyError):
            log_info('No directed-identifier supplied')
            return self.invalid()

        # Get the addon and user information from the installed table.
        try:
            uuid = receipt['user']['value']
        except KeyError:
            # If somehow we got a valid receipt without a uuid
            # that's a problem. Log here.
            log_info('No user in receipt')
            return self.invalid()

        try:
            storedata = receipt['product']['storedata']
            self.addon_id = int(dict(parse_qsl(storedata)).get('id', ''))
        except:
            # There was some value for storedata but it was invalid.
            log_info('Invalid store data')
            return self.invalid()

        sql = """SELECT id, user_id, premium_type FROM users_install
                 WHERE addon_id = %(addon_id)s
                 AND uuid = %(uuid)s LIMIT 1;"""
        self.cursor.execute(sql, {'addon_id': self.addon_id,
                                  'uuid': uuid})
        result = self.cursor.fetchone()
        if not result:
            # We've got no record of this receipt being created.
            log_info('No entry in users_install for uuid: %s' % uuid)
            return self.invalid()

        rid, self.user_id, self.premium = result

        # If it's a premium addon, then we need to get that the purchase
        # information.
        if self.premium != ADDON_PREMIUM:
            log_info('Valid receipt, not premium')
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
                log_info('Invalid receipt, no purchase')
                return self.invalid()

            if result[-1] in [CONTRIB_REFUND, CONTRIB_CHARGEBACK]:
                log_info('Valid receipt, but refunded')
                return self.refund()

            elif result[-1] == CONTRIB_PURCHASE:
                log_info('Valid receipt')
                return self.ok_or_expired(receipt)

            else:
                log_info('Valid receipt, but invalid contribution')
                return self.invalid()

    def invalid(self):
        return json.dumps({'status': 'invalid'})

    def ok_or_expired(self, receipt):
        # This receipt is ok now let's check it's expiry.
        # If it's expired, we'll have to return a new receipt
        try:
            expire = int(receipt.get('exp', 0))
        except ValueError:
            log_info('Error with expiry in the receipt')
            return self.expired(receipt)

        now = calendar.timegm(gmtime()) + 10  # For any clock skew.
        if now > expire:
            log_info('This receipt has expired: %s UTC < %s UTC'
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


def get_headers(length):
    return [('Access-Control-Allow-Origin', '*'),
            ('Access-Control-Allow-Methods', 'POST'),
            ('Content-Type', 'application/json'),
            ('Content-Length', str(length)),
            ('Cache-Control', 'no-cache'),
            ('Last-Modified', format_date_time(time()))]


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


def status_check(environ):
    output = ''
    # Check we can read from the users_install table, should be nice and
    # fast. Anything that fails here, connecting to db, accessing table
    # will be an error we need to know about.
    try:
        conn = mypool.connect()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users_install ORDER BY id DESC LIMIT 1')
    except Exception, err:
        return 500, str(err)

    return 200, output


def receipt_check(environ):
    output = ''
    with statsd.timer('services.verify'):
        data = environ['wsgi.input'].read()
        try:
            verify = Verify(data, environ)
            return 200, verify()
        except:
            log_exception('<none>')
            return 500, ''
    return output


def application(environ, start_response):
    body = ''
    path = environ.get('PATH_INFO', '')
    if path == '/services/status/':
        status, body = status_check(environ)
    else:
        # Only allow POST through as per spec.
        if environ.get('REQUEST_METHOD') != 'POST':
            status = 405
        else:
            status, body = receipt_check(environ)
    start_response(status_codes[status], get_headers(len(body)))
    return [body]
