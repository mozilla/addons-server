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


def record_action(action, request, data=None):
    """Records the given action by sending it to the metrics servers.

    Currently this is sending the data to the metrics servers and storing this
    data internally in the monolith temporary table.

    :param action: the action related to this request.
    :param request: the request that triggered this call.
    :param data: some optional additional data about this call.

    """
    if data is None:
        data = {}

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
