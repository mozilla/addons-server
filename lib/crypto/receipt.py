import urllib2

from django.conf import settings
from django_statsd.clients import statsd

import commonware.log

log = commonware.log.getLogger('z.services')


# TODO: insert some CEF logging into here.
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

    #TODO: see how rtilder wants this encoded, jwt, json, text, wasn't clear
    # to me from the Wiki.
    headers = {'Content-Type': 'application/json'}
    request = urllib2.Request(destination, receipt, headers)

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

