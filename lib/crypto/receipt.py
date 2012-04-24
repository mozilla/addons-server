import json
import urllib2

from django.conf import settings
from django.http import HttpRequest
from django_statsd.clients import statsd

from cef import log_cef as _log_cef
import commonware.log

log = commonware.log.getLogger('z.services')


class SigningError(Exception):
    pass


def sign(receipt):
    """
    Send the receipt to the signing service.

    This could possibly be made async via celery.
    """
    destination = settings.SIGNING_SERVER
    # If no destination is set. Just ignore this request.
    if not destination:
        return

    destination += '/1.0/sign'
    timeout = settings.SIGNING_SERVER_TIMEOUT

    log.info('Calling service: %s' % destination)
    headers = {'Content-Type': 'application/json'}
    data = receipt if isinstance(receipt, basestring) else json.dumps(receipt)
    request = urllib2.Request(destination, data, headers)

    try:
        with statsd.timer('services.sign'):
            response = urllib2.urlopen(request, timeout=timeout)
    except urllib2.HTTPError, error:
        # Will occur when a 3xx or greater code is returned
        log.error('Posting to signing failed: %s'
                  % (error.code))
        raise SigningError
    except:
        # Will occur when some other error occurs.
        log.error('Posting to signing failed', exc_info=True)
        raise SigningError

    if response.status_code != 200:
        log.error('Posting to signing failed: %s'
                  % (response.status_code))
        raise SigningError

    return response.read()


def decode(receipt):
    """
    Decode and verify that the receipt is sound from a crypto point of view.
    Will raise errors if the receipt is not valid, returns receipt contents
    if it is valid.
    """
    raise NotImplementedError


def cef(environ, app, msg, longer):
    """Log receipt transactions to the CEF library."""
    c = {'cef.product': getattr(settings, 'CEF_PRODUCT', 'AMO'),
         'cef.vendor': getattr(settings, 'CEF_VENDOR', 'Mozilla'),
         'cef.version': getattr(settings, 'CEF_VERSION', '0'),
         'cef.device_version': getattr(settings, 'CEF_DEVICE_VERSION', '0'),
         'cef.file': getattr(settings, 'CEF_FILE', 'syslog'), }

    kwargs = {'username': getattr(environ, 'amo_user', ''),
              'signature': 'RECEIPT%s' % msg.upper(),
              'msg': longer, 'config': c,
              'cs2': app, 'cs2Label': 'ReceiptTransaction'}

    if isinstance(environ, HttpRequest):
        environ = environ.META.copy()
    return _log_cef('Receipt %s' % msg, 5, environ, **kwargs)
