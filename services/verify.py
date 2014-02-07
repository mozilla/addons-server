import calendar
import json

from datetime import datetime
from time import gmtime, time
from urlparse import parse_qsl, urlparse
from wsgiref.handlers import format_date_time


from utils import (log_configure, log_exception, log_info, mypool,
                   ADDON_PREMIUM, CONTRIB_CHARGEBACK, CONTRIB_NO_CHARGE,
                   CONTRIB_PURCHASE, CONTRIB_REFUND)

from services.utils import settings

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


class InvalidReceipt(Exception):
    """
    InvalidReceipt takes a message, which is then displayed back to the app so
    they can understand the failure.
    """
    pass


class RefundedReceipt(Exception):
    pass


class Verify:

    def __init__(self, receipt, environ):
        self.receipt = receipt
        self.environ = environ
        # These will be extracted from the receipt.
        self.decoded = None
        self.addon_id = None
        self.user_id = None
        self.premium = None
        # This is so the unit tests can override the connection.
        self.conn, self.cursor = None, None

    def setup_db(self):
        if not self.cursor:
            self.conn = mypool.connect()
            self.cursor = self.conn.cursor()

    def check_full(self):
        """
        This is the default that verify will use, this will
        do the entire stack of checks.
        """
        receipt_domain = urlparse(settings.WEBAPPS_RECEIPT_URL).netloc
        try:
            self.decoded = self.decode()
            self.check_type('purchase-receipt')
            self.check_db()
            self.check_url(receipt_domain)
        except InvalidReceipt, err:
            return self.invalid(str(err))

        if self.premium != ADDON_PREMIUM:
            log_info('Valid receipt, not premium')
            return self.ok_or_expired()

        try:
            self.check_purchase()
        except InvalidReceipt, err:
            return self.invalid(str(err))
        except RefundedReceipt:
            return self.refund()

        return self.ok_or_expired()

    def check_without_purchase(self):
        """
        This is what the developer and reviewer receipts do, we aren't
        expecting a purchase, but require a specific type and install.
        """
        try:
            self.decoded = self.decode()
            self.check_type('developer-receipt', 'reviewer-receipt')
            self.check_db()
            self.check_url(settings.DOMAIN)
        except InvalidReceipt, err:
            return self.invalid(str(err))

        return self.ok_or_expired()

    def check_without_db(self, status):
        """
        This is what test receipts do, no purchase or install check.
        In this case the return is custom to the caller.
        """
        assert status in ['ok', 'expired', 'invalid', 'refunded']

        try:
            self.decoded = self.decode()
            self.check_type('test-receipt')
            self.check_url(settings.DOMAIN)
        except InvalidReceipt, err:
            return self.invalid(str(err))

        return getattr(self, status)()

    def decode(self):
        """
        Verifies that the receipt can be decoded and that the initial
        contents of the receipt are correct.

        If its invalid, then just return invalid rather than give out any
        information.
        """
        try:
            receipt = decode_receipt(self.receipt)
        except:
            log_exception({'receipt': '%s...' % self.receipt[:10],
                           'addon': self.addon_id})
            log_info('Error decoding receipt')
            raise InvalidReceipt('ERROR_DECODING')

        try:
            assert receipt['user']['type'] == 'directed-identifier'
        except (AssertionError, KeyError):
            log_info('No directed-identifier supplied')
            raise InvalidReceipt('NO_DIRECTED_IDENTIFIER')

        return receipt

    def check_type(self, *types):
        """
        Verifies that the type of receipt is what we expect.
        """
        if self.decoded.get('typ', '') not in types:
            log_info('Receipt type not in %s' % ','.join(types))
            raise InvalidReceipt('WRONG_TYPE')

    def check_url(self, domain):
        """
        Verifies that the URL of the verification is what we expect.

        :param domain: the domain you expect the receipt to be verified at,
            note that "real" receipts are verified at a different domain
            from the main marketplace domain.
        """
        path = self.environ['PATH_INFO']
        parsed = urlparse(self.decoded.get('verify', ''))

        if parsed.netloc != domain:
            log_info('Receipt had invalid domain')
            raise InvalidReceipt('WRONG_DOMAIN')

        if parsed.path != path:
            log_info('Receipt had the wrong path')
            raise InvalidReceipt('WRONG_PATH')

    def check_db(self):
        """
        Verifies the decoded receipt against the database.

        Requires that decode is run first.
        """
        if not self.decoded:
            raise ValueError('decode not run')

        self.setup_db()
        # Get the addon and user information from the installed table.
        try:
            uuid = self.decoded['user']['value']
        except KeyError:
            # If somehow we got a valid receipt without a uuid
            # that's a problem. Log here.
            log_info('No user in receipt')
            raise InvalidReceipt('NO_USER')

        try:
            storedata = self.decoded['product']['storedata']
            self.addon_id = int(dict(parse_qsl(storedata)).get('id', ''))
        except:
            # There was some value for storedata but it was invalid.
            log_info('Invalid store data')
            raise InvalidReceipt('WRONG_STOREDATA')

        sql = """SELECT id, user_id, premium_type FROM users_install
                 WHERE addon_id = %(addon_id)s
                 AND uuid = %(uuid)s LIMIT 1;"""
        self.cursor.execute(sql, {'addon_id': self.addon_id,
                                  'uuid': uuid})
        result = self.cursor.fetchone()
        if not result:
            # We've got no record of this receipt being created.
            log_info('No entry in users_install for uuid: %s' % uuid)
            raise InvalidReceipt('WRONG_USER')

        pk, self.user_id, self.premium = result

    def check_purchase(self):
        """
        Verifies that the app has been purchased.
        """
        sql = """SELECT id, type FROM addon_purchase
                 WHERE addon_id = %(addon_id)s
                 AND user_id = %(user_id)s LIMIT 1;"""
        self.cursor.execute(sql, {'addon_id': self.addon_id,
                                  'user_id': self.user_id})
        result = self.cursor.fetchone()
        if not result:
            log_info('Invalid receipt, no purchase')
            raise InvalidReceipt('NO_PURCHASE')

        if result[-1] in (CONTRIB_REFUND, CONTRIB_CHARGEBACK):
            log_info('Valid receipt, but refunded')
            raise RefundedReceipt

        elif result[-1] in (CONTRIB_PURCHASE, CONTRIB_NO_CHARGE):
            log_info('Valid receipt')
            return

        else:
            log_info('Valid receipt, but invalid contribution')
            raise InvalidReceipt('WRONG_PURCHASE')

    def invalid(self, reason=''):
        receipt_cef.log(self.environ, self.addon_id, 'verify',
                        'Invalid receipt')
        return json.dumps({'status': 'invalid', 'reason': reason})

    def ok_or_expired(self):
        # This receipt is ok now let's check it's expiry.
        # If it's expired, we'll have to return a new receipt
        try:
            expire = int(self.decoded.get('exp', 0))
        except ValueError:
            log_info('Error with expiry in the receipt')
            return self.expired()

        now = calendar.timegm(gmtime()) + 10  # For any clock skew.
        if now > expire:
            log_info('This receipt has expired: %s UTC < %s UTC'
                     % (datetime.utcfromtimestamp(expire),
                        datetime.utcfromtimestamp(now)))
            return self.expired()

        return self.ok()

    def ok(self):
        return json.dumps({'status': 'ok'})

    def refund(self):
        receipt_cef.log(self.environ, self.addon_id, 'verify',
                        'Refunded receipt')
        return json.dumps({'status': 'refunded'})

    def expired(self):
        receipt_cef.log(self.environ, self.addon_id, 'verify',
                        'Expired receipt')
        if settings.WEBAPPS_RECEIPT_EXPIRED_SEND:
            self.decoded['exp'] = (calendar.timegm(gmtime()) +
                              settings.WEBAPPS_RECEIPT_EXPIRY_SECONDS)
            # Log that we are signing a new receipt as well.
            receipt_cef.log(self.environ, self.addon_id, 'sign',
                            'Expired signing request')
            return json.dumps({'status': 'expired',
                               'receipt': sign(self.decoded)})
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
            verifier = certs.ReceiptVerifier(valid_issuers=
                                             settings.SIGNING_VALID_ISSUERS)
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
    if not settings.SIGNING_SERVER_ACTIVE:
        return 500, 'SIGNING_SERVER_ACTIVE is not set'

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
            return 200, verify.check_full()
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
