import hashlib
import urlparse
import uuid

import commonware.log
from moz_inapp_pay.verify import verify_claims, verify_keys

import jwt


log = commonware.log.getLogger('z.crypto')
secret = 'marketplaceSecret'  # This is a placeholder.


class InvalidSender(Exception):
    pass


def get_uuid():
    return 'bluevia:%s' % hashlib.md5(str(uuid.uuid4())).hexdigest()


def verify_bluevia_jwt(signed_jwt):
    # This can probably be deleted depending upon solitude.
    try:
        jwt.decode(signed_jwt.encode('ascii'), secret)
    except Exception, e:
        log.error('Error decoding bluevia jwt: %s' % e, exc_info=True)
        return {'valid': False}
    return {'valid': True}


def sign_bluevia_jwt(data):
    return jwt.encode(data, secret)


def parse_from_bluevia(signed_jwt, ip):
    try:
        data = jwt.decode(signed_jwt.encode('ascii'), secret)
    except Exception, e:
        log.info('Received invalid bluevia postback from IP %s: %s' %
                 (ip or '(unknown)', e), exc_info=True)
        raise InvalidSender()

    verify_claims(data)
    iss, aud, product_data, trans_id = verify_keys(data,
                                            ('iss', 'aud',
                                             'request.productData',
                                             'response.transactionID'))
    log.info('Received BlueVia postback JWT: iss:%s aud:%s '
             'trans_id:%s product_data:%s'
             % (iss, aud, trans_id, product_data))
    return data
