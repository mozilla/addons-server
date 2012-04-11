import json
import urllib2
import uuid

from django.conf import settings

from celeryutils import task
import commonware.log

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
    namespace = settings.DOMAIN.replace('.', '_') + action

    destination = '%s/%s/%s' % (destination, namespace, uid)
    headers = {'Content-Type': 'application/json'}
    request = urllib2.Request(destination, data, headers)

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

    # Catches codes that are 2xx but not 200.
    if response.status_code != 200:
        log.error('Posting to metrics failed: %s, uuid: %s'
                  % (response.status_code, uid))

    return response.status_code
