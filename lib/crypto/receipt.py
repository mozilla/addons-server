import json
import urllib2

from django.conf import settings
from django_statsd.clients import statsd

from cef import log_cef as _log_cef
import commonware.log

log = commonware.log.getLogger('z.services')


def sign(receipt):
    """
    Send the receipt to the signing service.

    This could possibly be made async via celery.
    """
    destination = settings.SIGNING_SERVER
    # If no destination is set. Just ignore this request.
    if not destination:
        return

    timeout = settings.SIGNING_SERVER_TIMEOUT

    headers = {'Content-Type': 'application/json'}
    request = urllib2.Request(destination, json.dumps(receipt), headers)

    try:
        with statsd.timer('services.sign'):
            response = urllib2.urlopen(request, timeout=timeout)
    except urllib2.HTTPError, error:
        # Will occur when a 3xx or greater code is returned
        log.error('Posting to signing failed: %s'
                  % (error.code))
        return error.code
    except:
        # Will occur when some other error occurs.
        log.error('Posting to signing failed', exc_info=True)
        return

    # The list of valid statuses are here:
    # https://wiki.mozilla.org/Apps/WebApplicationReceipt/SigningService
    if response.status_code not in [400, 401, 409, 503]:
        log.error('Posting to signing failed: %s'
                  % (response.status_code))

    return response.status_code


def decode(receipt):
    """
    Decode and verify that the receipt is sound from a crypto point of view.
    Will raise errors if the receipt is not valid, returns receipt contents
    if it is valid.
    """
    raise NotImplementedError


def cef(request, app, msg, longer):
    """Log receipt transactions to the CEF library."""

def log_cef(request, app, msg, longer):
    """Log receipt transactions to the CEF library."""
    c = {'cef.product': getattr(settings, 'CEF_PRODUCT', 'AMO'),
         'cef.vendor': getattr(settings, 'CEF_VENDOR', 'Mozilla'),
         'cef.version': getattr(settings, 'CEF_VERSION', '0'),
         'cef.device_version': getattr(settings, 'CEF_DEVICE_VERSION', '0'),
         'cef.file': getattr(settings, 'CEF_FILE', 'syslog'), }

    kwargs = {'username': getattr(request, 'amo_user', ''),
              'signature': 'RECEIPT%s' % msg.upper(),
              'msg': longer, 'config': c,
              'cs2': app, 'cs2Label': 'ReceiptTransaction'}
    return _log_cef('Receipt %s' % msg, 5, request, **kwargs)
