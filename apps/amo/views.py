import socket
import urllib2

from django import http
from django.conf import settings
from django.core.cache import parse_backend_uri
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

import jingo
import phpserialize as php

from stats.models import Contribution, ContributionError
from . import log


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
                status = 500
                log.critical('Failed to connect to memcached (%s): %s' %
                                                                    (host, e))
            else:
                result = True
            finally:
                s.close()

            memcache_results.append((ip, port, result))
        if len(memcache_results) < 2:
            status = 500
            status_summary['memcache'] = False
            log.warning('You should have 2+ memcache servers.  You have %s.' %
                                                        len(memcache_results))
    if not memcache_results:
        status = 500
        status_summary['memcache'] = False
        log.info('Memcache is not configured.')

    return jingo.render(request, 'services/monitor.html',
                        {'memcache_results': memcache_results,
                         'status_summary': status_summary},
                        status=status)


@csrf_exempt
def paypal(request):
    """
    Handle PayPal IPN post-back for contribution transactions.

    IPN will retry periodically until it gets success (status=200). Any
    db errors or replication lag will result in an exception and http
    status of 500, which is good so PayPal will try again later.
    """

    # Check that the request is valid and coming from PayPal.
    data = request.POST.copy()
    data['cmd'] = '_notify-validate'
    if urllib2.urlopen(settings.PAYPAL_CGI_URL,
                       data.urlencode(), 20).readline() != 'VERIFIED':
        return http.HttpResponseForbidden('Invalid confirmation')

    # We only care about completed transactions.
    if request.POST['payment_status'] != 'Completed':
        return http.HttpResponse('Payment not completed')

    # Make sure transaction has not yet been processed.
    if len(Contribution.objects.filter(transaction_id=request.POST['txn_id'])) > 0:
        return http.HttpResponse('Transaction already processed')

    # Fetch and update the contribution - item_number is the uuid we created.
    try:
        c = Contribution.objects.get(uuid=request.POST['item_number'])
    except Contribution.DoesNotExist:
        # If these warnings frequently occur on the first IPN attempt,
        # perhaps consider logging only if POST['resend'] is set.
        ipn_type = 'repeated' if 'resend' in request.POST else 'initial'
        log.warning('Contribution (uuid=%s) not found for %s IPN request.'
                     % (request.POST['item_number'], ipn_type))
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
        log.error('Thankyou note email failed with error: %s' % e)

    return http.HttpResponse('Success!')


def handler404(request):
    return jingo.render(request, 'amo/404.lhtml', status=404)


def handler500(request):
    return jingo.render(request, 'amo/500.lhtml', status=500)
