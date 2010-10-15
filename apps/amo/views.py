import json
import os
import random
from PIL import Image
import socket
import StringIO
import time
import urllib2
from urlparse import urlparse

from django import http
from django.conf import settings
from django.core.cache import cache, parse_backend_uri
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

import caching.invalidation
import celery.task
import commonware.log
import jingo
import phpserialize as php

import amo
import mongoutils
from hera.contrib.django_utils import get_hera
from stats.models import Contribution, ContributionError, SubscriptionEvent
from . import log

paypal_log = commonware.log.getLogger('z.paypal')
csp_log = commonware.log.getLogger('z.csp')


def check_redis():
    redis = caching.invalidation.get_redis_backend()
    try:
        return redis.info(), None
    except Exception, e:
        log.critical('Failed to chat with redis: (%s)' % e)
        return None, e


@never_cache
def monitor(request):

    # For each check, a boolean pass/fail status to show in the template
    status_summary = {}
    status = 200

    # Check all memcached servers
    scheme, servers, _ = parse_backend_uri(settings.CACHE_BACKEND)
    memcache_results = []
    status_summary['memcache'] = True
    if 'memcached' in scheme:
        hosts = servers.split(';')
        for host in hosts:
            ip, port = host.split(':')
            try:
                s = socket.socket()
                s.connect((ip, int(port)))
            except Exception, e:
                result = False
                status_summary['memcache'] = False
                log.critical('Failed to connect to memcached (%s): %s' %
                                                                    (host, e))
            else:
                result = True
            finally:
                s.close()

            memcache_results.append((ip, port, result))
        if len(memcache_results) < 2:
            status_summary['memcache'] = False
            log.warning('You should have 2+ memcache servers.  You have %s.' %
                                                        len(memcache_results))
    if not memcache_results:
        status_summary['memcache'] = False
        log.info('Memcache is not configured.')

    # Check Libraries and versions
    libraries_results = []
    status_summary['libraries'] = True
    try:
        Image.new('RGB', (16, 16)).save(StringIO.StringIO(), 'JPEG')
        libraries_results.append(('PIL+JPEG', True, 'Got it!'))
    except Exception, e:
        status_summary['libraries'] = False
        msg = "Failed to create a jpeg image: %s" % e
        libraries_results.append(('PIL+JPEG', False, msg))

    # Check file paths / permissions
    filepaths = (
        (settings.NETAPP_STORAGE, os.R_OK | os.W_OK, "We want read + write."),
        (settings.UPLOADS_PATH, os.R_OK | os.W_OK, "We want read + write."),
        (settings.ADDON_ICONS_PATH,
            os.R_OK | os.W_OK, "We want read + write."),
        (settings.COLLECTIONS_ICON_PATH,
            os.R_OK | os.W_OK, "We want read + write."),
        (settings.PREVIEWS_PATH, os.R_OK | os.W_OK, "We want read + write."),
        (settings.USERPICS_PATH, os.R_OK | os.W_OK, "We want read + write."),
    )
    filepath_results = []
    filepath_status = True

    for path, perms, notes in filepaths:
        path_exists = os.path.isdir(path)
        path_perms = os.access(path, perms)
        filepath_status = filepath_status and path_exists and path_perms
        filepath_results.append((path, path_exists, path_perms, notes))

    status_summary['filepaths'] = filepath_status

    # Check Redis
    redis_results = [None, 'REDIS_BACKEND is not set']
    if getattr(settings, 'REDIS_BACKEND', False):
        redis_results = check_redis()
    status_summary['redis'] = bool(redis_results[0])

    # Check Hera
    hera_results = []
    status_summary['hera'] = True
    for i in settings.HERA:
        r = {'location': urlparse(i['LOCATION'])[1],
             'result': bool(get_hera(i))}
        hera_results.append(r)
        if not hera_results[-1]['result']:
            status_summary['hera'] = False

    # Check Rabbit
    # start = time.time()
    # pong = celery.task.ping()
    # rabbit_results = r = {'duration': time.time() - start}
    # status_summary['rabbit'] = pong == 'pong' and r['duration'] < 1

    # Check Mongo
    mongo_results = []
    status_summary['mongo'] = mongoutils.connect_mongo()

    # If anything broke, send HTTP 500
    if not all(status_summary):
        status = 500

    return jingo.render(request, 'services/monitor.html',
                        {'memcache_results': memcache_results,
                         'libraries_results': libraries_results,
                         'filepath_results': filepath_results,
                         'redis_results': redis_results,
                         'hera_results': hera_results,
                         'mongo_results': mongo_results,
                         # 'rabbit_results': rabbit_results,
                         'status_summary': status_summary},
                        status=status)


def robots(request):
    """Generate a robots.txt"""
    if not settings.ENGAGE_ROBOTS:
        template = "Disallow: /"
    else:
        template = jingo.render(request, 'amo/robots.html',
                                {'apps': amo.APP_USAGE})

    return HttpResponse(template, mimetype="text/plain")


@csrf_exempt
def paypal(request):
    """
    Handle PayPal IPN post-back for contribution transactions.

    IPN will retry periodically until it gets success (status=200). Any
    db errors or replication lag will result in an exception and http
    status of 500, which is good so PayPal will try again later.

    PayPal IPN variables available at:
    https://cms.paypal.com/us/cgi-bin/?cmd=_render-content
                    &content_ID=developer/e_howto_html_IPNandPDTVariables
    """
    try:
        return _paypal(request)
    except Exception, e:
        paypal_log.error('%s\n%s' % (e, request))
        return http.HttpResponseServerError('Unknown error.')


def _paypal(request):

    def _log_error_with_data(msg, request):
        """Log a message along with some of the POST info from PayPal."""

        id = random.randint(0, 99999999)
        msg = "[%s] %s (dumping data)" % (id, msg)

        paypal_log.error(msg)

        logme = {'txn_id': request.POST.get('txn_id'),
                 'txn_type': request.POST.get('txn_type'),
                 'payer_email': request.POST.get('payer_email'),
                 'receiver_email': request.POST.get('receiver_email'),
                 'payment_status': request.POST.get('payment_status'),
                 'payment_type': request.POST.get('payment_type'),
                 'mc_gross': request.POST.get('mc_gross'),
                 'item_number': request.POST.get('item_number'),
                }

        paypal_log.error("[%s] PayPal Data: %s" % (id, logme))

    if request.method != 'POST':
        return http.HttpResponseNotAllowed(['POST'])

    # Check that the request is valid and coming from PayPal.
    data = '%s&%s' % ('cmd=_notify-validate', request.raw_post_data)
    paypal_response = urllib2.urlopen(settings.PAYPAL_CGI_URL,
                                      data, 20).readline()
    if paypal_response != 'VERIFIED':
        msg = ("Expecting 'VERIFIED' from PayPal, got '%s'. "
               "Failing." % paypal_response)
        _log_error_with_data(msg, request)
        return http.HttpResponseForbidden('Invalid confirmation')

    if request.POST.get('txn_type', '').startswith('subscr_'):
        SubscriptionEvent.objects.create(post_data=php.serialize(request.POST))
        return http.HttpResponse('Success!')

    # We only care about completed transactions.
    if request.POST.get('payment_status') != 'Completed':
        return http.HttpResponse('Payment not completed')

    # Make sure transaction has not yet been processed.
    if (Contribution.objects
                   .filter(transaction_id=request.POST['txn_id']).count()) > 0:
        return http.HttpResponse('Transaction already processed')

    # Fetch and update the contribution - item_number is the uuid we created.
    try:
        c = Contribution.objects.get(uuid=request.POST['item_number'])
    except Contribution.DoesNotExist:
        key = "%s%s:%s" % (settings.CACHE_PREFIX, 'contrib',
                           request.POST['item_number'])
        count = cache.get(key, 0) + 1

        paypal_log.warning('Contribution (uuid=%s) not found for IPN request '
                           '#%s.' % (request.POST['item_number'], count))
        if count > 10:
            msg = ("Paypal sent a transaction that we don't know "
                   "about and we're giving up on it.")
            _log_error_with_data(msg, request)
            cache.delete(key)
            return http.HttpResponse('Transaction not found; skipping.')
        cache.set(key, count, 1209600)  # This is 2 weeks.
        return http.HttpResponseServerError('Contribution not found')

    c.transaction_id = request.POST['txn_id']
    c.amount = request.POST['mc_gross']
    c.uuid = None
    c.post_data = php.serialize(request.POST)
    c.save()

    # Send thankyou email.
    try:
        c.mail_thankyou(request)
    except ContributionError as e:
        # A failed thankyou email is not a show stopper, but is good to know.
        paypal_log.error('Thankyou note email failed with error: %s' % e)

    return http.HttpResponse('Success!')


def handler404(request):
    return jingo.render(request, 'amo/404.lhtml', status=404)


def handler500(request):
    return jingo.render(request, 'amo/500.lhtml', status=500)


def loaded(request):
    return http.HttpResponse('%s' % request.META['wsgi.loaded'],
                             content_type='text/plain')


@csrf_exempt
@require_POST
def cspreport(request):
    """Accept CSP reports and log them."""
    try:
        v = json.loads(request.raw_post_data)['csp-report']
        msg = ("CSP Violation Report:  (Request: %s) (Blocked: %s) (Rule: %s)"
               % (v['request'], v['blocked-uri'], v['violated-directive']))
        csp_log.warning(msg)
    except Exception:
        csp_log.debug("Got a malformed violation report.  Ignoring...")
        return HttpResponseBadRequest()

    return HttpResponse()
