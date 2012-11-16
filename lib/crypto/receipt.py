import json
import urllib2

from django.conf import settings
from django_statsd.clients import statsd

import commonware.log

import jwt


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

    receipt_json = json.dumps(receipt)
    log.info('Calling service: %s' % destination)
    log.info('Receipt contents: %s' % receipt_json)
    headers = {'Content-Type': 'application/json'}
    data = receipt if isinstance(receipt, basestring) else receipt_json
    request = urllib2.Request(destination, data, headers)

    try:
        with statsd.timer('services.sign.receipt'):
            response = urllib2.urlopen(request, timeout=timeout)
    except urllib2.HTTPError, error:
        # Will occur when a 3xx or greater code is returned
        log.error('Posting to receipt signing failed: %s, %s'
                  % (error.code, error.read().strip()))
        raise SigningError('Posting to receipt signing failed: %s, %s'
                           % (error.code, error.read().strip()))
    except:
        # Will occur when some other error occurs.
        log.error('Posting to receipt signing failed', exc_info=True)
        raise SigningError('Posting receipt signing failed')

    if response.getcode() != 200:
        log.error('Posting to signing failed: %s'
                  % (response.getcode()))
        raise SigningError('Posting to signing failed: %s'
                           % (response.getcode()))

    return json.loads(response.read())['receipt']


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
