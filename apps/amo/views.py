import json
import random
import urllib2

from django import http
from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

import commonware.log
import jingo
import phpserialize as php
import waffle
from django_arecibo.tasks import post
from statsd import statsd

import amo
import files.tasks
from amo.decorators import post_required
from stats.models import Contribution, ContributionError, SubscriptionEvent
from . import monitors

monitor_log = commonware.log.getLogger('z.monitor')
paypal_log = commonware.log.getLogger('z.paypal')
csp_log = commonware.log.getLogger('z.csp')
jp_log = commonware.log.getLogger('z.jp.repack')


@never_cache
def monitor(request, format=None):

    # For each check, a boolean pass/fail status to show in the template
    status_summary = {}
    results = {}

    checks = ['memcache', 'libraries', 'elastic', 'path', 'redis', 'hera']

    for check in checks:
        with statsd.timer('monitor.%s' % check) as timer:
            status, result = getattr(monitors, check)()
        status_summary[check] = status
        results['%s_results' % check] = result
        results['%s_timer' % check] = timer.ms

    # If anything broke, send HTTP 500.
    status_code = 200 if all(status_summary.values()) else 500

    if format == '.json':
        return http.HttpResponse(json.dumps(status_summary),
                                 status=status_code)
    ctx = {}
    ctx.update(results)
    ctx['status_summary'] = status_summary

    return jingo.render(request, 'services/monitor.html',
                        ctx, status=status_code)


def robots(request):
    """Generate a robots.txt"""
    _service = (request.META['SERVER_NAME'] == settings.SERVICES_DOMAIN)
    if _service or not settings.ENGAGE_ROBOTS:
        template = "User-agent: *\nDisallow: /"
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

    # raw_post_data has to be accessed before request.POST. wtf django?
    raw, post = request.raw_post_data, request.POST.copy()

    # Check that the request is valid and coming from PayPal.
    # The order of the params has to match the original request.
    data = u'cmd=_notify-validate&' + raw
    paypal_response = urllib2.urlopen(settings.PAYPAL_CGI_URL,
                                      data, 20).readline()

    if paypal_response != 'VERIFIED':
        msg = ("Expecting 'VERIFIED' from PayPal, got '%s'. "
               "Failing." % paypal_response)
        _log_error_with_data(msg, request)
        return http.HttpResponseForbidden('Invalid confirmation')

    if post.get('txn_type', '').startswith('subscr_'):
        SubscriptionEvent.objects.create(post_data=php.serialize(post))
        return http.HttpResponse('Success!')

    # List of (old, new) codes so we can transpose the data for
    # embedded payments.
    for old, new in [('payment_status', 'status'),
                     ('item_number', 'tracking_id'),
                     ('txn_id', 'tracking_id'),
                     ('payer_email', 'sender_email')]:
        if old not in post and new in post:
            post[old] = post[new]

    # We only care about completed transactions.
    if post.get('payment_status', '').lower() != 'completed':
        return http.HttpResponse('Payment not completed')

    # Make sure transaction has not yet been processed.
    if (Contribution.objects
                   .filter(transaction_id=post['txn_id']).count()) > 0:
        return http.HttpResponse('Transaction already processed')

    # Fetch and update the contribution - item_number is the uuid we created.
    try:
        c = Contribution.objects.get(uuid=post['item_number'])
    except Contribution.DoesNotExist:
        key = "%s%s:%s" % (settings.CACHE_PREFIX, 'contrib',
                           post['item_number'])
        count = cache.get(key, 0) + 1

        paypal_log.warning('Contribution (uuid=%s) not found for IPN request '
                           '#%s.' % (post['item_number'], count))
        if count > 10:
            msg = ("Paypal sent a transaction that we don't know "
                   "about and we're giving up on it.")
            _log_error_with_data(msg, request)
            cache.delete(key)
            return http.HttpResponse('Transaction not found; skipping.')
        cache.set(key, count, 1209600)  # This is 2 weeks.
        return http.HttpResponseServerError('Contribution not found')

    c.transaction_id = post['txn_id']
    # Embedded payments does not send an mc_gross.
    if 'mc_gross' in post:
        c.amount = post['mc_gross']
    c.uuid = None
    c.post_data = php.serialize(post)
    c.save()

    # Send thankyou email.
    try:
        c.mail_thankyou(request)
    except ContributionError as e:
        # A failed thankyou email is not a show stopper, but is good to know.
        paypal_log.error('Thankyou note email failed with error: %s' % e)

    return http.HttpResponse('Success!')


def handler404(request):
    return jingo.render(request, 'amo/404.html', status=404)


def handler500(request):
    arecibo = getattr(settings, 'ARECIBO_SERVER_URL', '')
    if arecibo:
        post(request, 500)
    return jingo.render(request, 'amo/500.html', status=500)


def csrf_failure(request, reason=''):
    return jingo.render(request, 'amo/403.html',
                        {'csrf': 'CSRF' in reason}, status=403)


def loaded(request):
    return http.HttpResponse('%s' % request.META['wsgi.loaded'],
                             content_type='text/plain')


@csrf_exempt
@require_POST
def cspreport(request):
    """Accept CSP reports and log them."""
    report = ('blocked-uri', 'violated-directive', 'original-policy')

    if not waffle.sample_is_active('csp-store-reports'):
        return HttpResponse()

    try:
        v = json.loads(request.raw_post_data)['csp-report']
        # CEF module wants a dictionary of environ, we want request
        # to be the page with error on it, that's contained in the csp-report.
        meta = request.META.copy()
        method, url = v['request'].split(' ', 1)
        meta.update({'REQUEST_METHOD': method, 'PATH_INFO': url})
        v = [(k, v[k]) for k in report if k in v]
        # This requires you to use the cef.formatter to get something nice out.
        csp_log.warning('Violation', dict(environ=meta,
                                          product='addons',
                                          username=request.user,
                                          data=v))
    except Exception:
        return HttpResponseBadRequest()

    return HttpResponse()


@csrf_exempt
@post_required
def builder_pingback(request):
    data = dict(request.POST.items())
    jp_log.info('Pingback from builder: %r' % data)
    try:
        # We expect all these attributes to be available.
        attrs = 'result msg location secret request'.split()
        for attr in attrs:
            assert attr in data, '%s not in %s' % (attr, data)
        # Only AMO and the builder should know this secret.
        assert data.get('secret') == settings.BUILDER_SECRET_KEY
    except Exception:
        jp_log.warning('Problem with builder pingback.', exc_info=True)
        return http.HttpResponseBadRequest()
    files.tasks.repackage_jetpack(data)
    return http.HttpResponse()


def graphite(request, site):
    ctx = {'width': 586, 'height': 308}
    ctx.update(request.GET.items())
    ctx['site'] = site
    return jingo.render(request, 'services/graphite.html', ctx)
