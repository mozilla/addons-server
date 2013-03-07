import hashlib
import uuid

from django.conf import settings

import commonware.log
from mozpay.verify import verify_claims, verify_keys

import jwt


log = commonware.log.getLogger('z.crypto')
secret = settings.APP_PURCHASE_SECRET


class InvalidSender(Exception):
    pass


def get_uuid():
    return 'webpay:%s' % hashlib.md5(str(uuid.uuid4())).hexdigest()


def verify_webpay_jwt(signed_jwt):
    # This can probably be deleted depending upon solitude.
    try:
        jwt.decode(signed_jwt.encode('ascii'), secret)
    except Exception, e:
        log.error('Error decoding webpay jwt: %s' % e, exc_info=True)
        return {'valid': False}
    return {'valid': True}


def sign_webpay_jwt(data):
    return jwt.encode(data, secret)


def parse_from_webpay(signed_jwt, ip):
    try:
        data = jwt.decode(signed_jwt.encode('ascii'), secret)
    except Exception, e:
        log.info('Received invalid webpay postback from IP %s: %s' %
                 (ip or '(unknown)', e), exc_info=True)
        raise InvalidSender()

    verify_claims(data)
    iss, aud, product_data, trans_id = verify_keys(
        data,
        ('iss', 'aud', 'request.productData', 'response.transactionID'))
    log.info('Received webpay postback JWT: iss:%s aud:%s '
             'trans_id:%s product_data:%s'
             % (iss, aud, trans_id, product_data))
    return data
