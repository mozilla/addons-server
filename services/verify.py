from email.Utils import formatdate
import json
import re
from time import time
from urlparse import parse_qsl

from utils import (log_configure, log_exception, log_info, mypool, settings,
                   CONTRIB_CHARGEBACK, CONTRIB_PURCHASE, CONTRIB_REFUND)

# Go configure the log.
log_configure()

import jwt
import M2Crypto
# This has to be imported after the settings (utils).
from statsd import statsd


class Verify:

    def __init__(self, addon_id, receipt):
        # The regex should ensure that only sane ints get to this point.
        self.addon_id = int(addon_id)
        self.receipt = receipt
        # This is so the unit tests can override the connection.
        self.conn, self.cursor = None, None

    def __call__(self):
        if not self.cursor:
            self.conn = mypool.connect()
            self.cursor = self.conn.cursor()

        # Try and decode the receipt data.
        # If its invalid, then just return invalid rather than give out any
        # information.
        try:
            receipt = decode_receipt(self.receipt)
        except (jwt.DecodeError, M2Crypto.RSA.RSAError), e:
            self.log('Error decoding receipt: %s' % e)
            return self.invalid()

        # Get the addon and user information from the installed table.
        try:
            email = receipt['user']['value']
        except KeyError:
            # If somehow we got a valid receipt without an email,
            # that's a problem. Log here.
            self.log('No user in receipt')
            return self.invalid()

        # Newer receipts have the addon_id in the storedata,
        # if it doesn't match the URL, then it's wrong.
        receipt_addon_id = None
        try:
            storedata = receipt['product']['storedata']
            receipt_addon_id = int(dict(parse_qsl(storedata)).get('id', ''))
        except (KeyError, TypeError):
            # At some point, we'll want to make this a hard failure,
            # before the beta of apps store. But doing so now will break
            # all of the existing receipts.
            if settings.WEBAPPS_RECEIPT_REQUIRE_STOREDATA:
                self.log('Invalid required store data')
                return self.invalid()
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
                 AND email = %(email)s LIMIT 1;"""
        self.cursor.execute(sql, {'addon_id': self.addon_id,
                                  'email': email})
        result = self.cursor.fetchone()
        if not result:
            # We've got no record of this receipt being created.
            self.log('No entry in users_install for email: %s' % email)
            return self.invalid()

        rid, user_id, premium = result

        # If it's a premium addon, then we need to get that the purchase
        # information.
        if not premium:
            self.log('Valid receipt, not premium')
            return self.ok(receipt)

        else:
            sql = """SELECT id, type FROM addon_purchase
                     WHERE addon_id = %(addon_id)s
                     AND user_id = %(user_id)s LIMIT 1;"""
            self.cursor.execute(sql, {'addon_id': self.addon_id,
                                      'user_id': user_id})
            result = self.cursor.fetchone()
            if not result:
                self.log('Invalid receipt, no purchase')
                return self.invalid()

            if result[-1] in [CONTRIB_REFUND, CONTRIB_CHARGEBACK]:
                self.log('Valid receipt, but refunded')
                return self.refund()

            elif result[-1] == CONTRIB_PURCHASE:
                self.log('Valid receipt')
                return self.ok(receipt)

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

    def ok(self, receipt):
        return json.dumps({'status': 'ok', 'receipt': receipt})

    def refund(self):
        return json.dumps({'status': 'refunded'})


def decode_receipt(receipt):
    """
    Cracks the receipt using the private key. This will probably change
    to using the cert at some point, especially when we get the HSM.
    """
    with statsd.timer('services.decode'):
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
            verify = Verify(addon_id, data)
            output = verify()
            start_response(status, verify.get_headers(len(output)))
        except:
            output = ''
            log_exception({'receipt': '%s...' % data[:10], 'addon': addon_id})
            start_response('500 Internal Server Error', [])

    return [output]
