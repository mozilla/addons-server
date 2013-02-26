import json
import re
import urllib2
from urlparse import urljoin
import uuid

from django.conf import settings

from celeryutils import task
import commonware.log

from mkt.monolith import record_stat

log = commonware.log.getLogger('z.metrics')


def send(action, data):
    """
    Logs some data and then sends it to the metrics cluster through a
    delayed celery task.
    """
    uid = str(uuid.uuid4())
    data = json.dumps(data)
    # This is the most reliable call we can make.
    log.info(u'%s|%s|%s' % (uid, action, data))
    # Do this async and if it fails we can re-run it again from the log.
    metrics.delay(uid, action, data)


def send_request(action, request, data):
    """
    Passes to send, but pulls what we'd like out of the request
    before doing so. Use this from Django views.
    """
    data['user-agent'] = request.META.get('HTTP_USER_AGENT')
    data['locale'] = request.LANG
    data['src'] = request.GET.get('src', '')
    record_stat(action, request, **data)
    send(action, data)


@task
def metrics(uid, action, data, **kw):
    """
    Actually sends the data to the server, done async in celery. If celery or
    the http ping fails, then we can recreate this from the log.

    Returns the status code or False if it failed to run.
    """
    destination = settings.METRICS_SERVER
    # If no destination is set. Just ignore this request.
    if not destination:
        return

    timeout = settings.METRICS_SERVER_TIMEOUT
    namespace = re.sub('\.|-', '_', settings.DOMAIN)

    destination = urljoin(destination, 'submit/%s_%s/%s'
                          % (namespace, action, uid))
    headers = {'Content-Type': 'application/json'}
    request = urllib2.Request(destination, data, headers)

    log.info('Calling metrics: %s' % destination)
    try:
        response = urllib2.urlopen(request, timeout=timeout)
    except urllib2.HTTPError, error:
        # Will occur when a 3xx or greater code is returned
        log.error('Posting to metrics failed: %s, uuid: %s'
                  % (error.code, uid))
        return error.code
    except:
        # Will occur when some other error occurs.
        log.error('Posting to metrics failed uuid: %s' % uid, exc_info=True)
        return

    # Catches codes that are 2xx but not 201.
    if response.getcode() != 201:
        log.error('Posting to metrics failed: %s, uuid: %s'
                  % (response.getcode(), uid))

    return response.getcode()
