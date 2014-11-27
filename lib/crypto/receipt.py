import json

from django.conf import settings
from django_statsd.clients import statsd

import commonware.log
import jwt
import requests


log = commonware.log.getLogger('z.crypto')


class SigningError(Exception):
    pass


def sign(receipt):
    """
    Send the receipt to the signing service.

    This could possibly be made async via celery.
    """
    # If no destination is set. Just ignore this request.
    if not settings.SIGNING_SERVER:
        return ValueError('Invalid config. SIGNING_SERVER empty.')

    destination = settings.SIGNING_SERVER + '/1.0/sign'
    timeout = settings.SIGNING_SERVER_TIMEOUT

    data = json.dumps(receipt)
    log.info('Calling service: %s' % destination)
    log.info('Receipt contents: %s' % data)
    headers = {'Content-Type': 'application/json'}
    data = receipt if isinstance(receipt, basestring) else data

    try:
        with statsd.timer('services.sign.receipt'):
            req = requests.post(destination, data=data, headers=headers,
                                timeout=timeout)
    except requests.Timeout:
        statsd.incr('services.sign.receipt.timeout')
        log.error('Posting to receipt signing timed out')
        raise SigningError('Posting to receipt signing timed out')
    except requests.RequestException:
        # Will occur when some other error occurs.
        statsd.incr('services.sign.receipt.error')
        log.error('Posting to receipt signing failed', exc_info=True)
        raise SigningError('Posting to receipt signing failed')

    if req.status_code != 200:
        statsd.incr('services.sign.receipt.error')
        log.error('Posting to signing failed: %s' % req.status_code)
        raise SigningError('Posting to signing failed: %s'
                           % req.status_code)

    return json.loads(req.content)['receipt']


def decode(receipt):
    """
    Decode and verify that the receipt is sound from a crypto point of view.
    Will raise errors if the receipt is not valid, returns receipt contents
    if it is valid.
    """
    raise NotImplementedError


def crack(receipt):
    """
    Crack open the receipt, without checking that the crypto is valid.
    Returns a list of all the elements of a receipt, which by default is
    cert, receipt.
    """
    return map(lambda x: jwt.decode(x.encode('ascii'), verify=False),
               receipt.split('~'))
