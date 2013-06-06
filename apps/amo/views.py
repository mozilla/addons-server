import json
import re

from django import http
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils.encoding import iri_to_uri
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

import commonware.log
import jingo
import waffle
from django_statsd.views import record as django_statsd_record
from django_statsd.clients import statsd

import amo
import api
import files.tasks
from amo.decorators import post_required
from amo.utils import log_cef
from amo.context_processors import get_collect_timings
from . import monitors

log = commonware.log.getLogger('z.amo')
monitor_log = commonware.log.getLogger('z.monitor')
jp_log = commonware.log.getLogger('z.jp.repack')

flash_re = re.compile(r'^(Win|(PPC|Intel) Mac OS X|Linux.+i\d86)|SunOs', re.IGNORECASE)
quicktime_re = re.compile(r'^(application/(sdp|x-(mpeg|rtsp|sdp))|audio/(3gpp(2)?|AMR|aiff|basic|mid(i)?|mp4|mpeg|vnd\.qcelp|wav|x-(aiff|m4(a|b|p)|midi|mpeg|wav))|image/(pict|png|tiff|x-(macpaint|pict|png|quicktime|sgi|targa|tiff))|video/(3gpp(2)?|flc|mp4|mpeg|quicktime|sd-video|x-mpeg))$')
java_re = re.compile(r'^application/x-java-((applet|bean)(;jpi-version=1\.5|;version=(1\.(1(\.[1-3])?|(2|4)(\.[1-2])?|3(\.1)?|5)))?|vm)$')
wmp_re = re.compile(r'^(application/(asx|x-(mplayer2|ms-wmp))|video/x-ms-(asf(-plugin)?|wm(p|v|x)?|wvx)|audio/x-ms-w(ax|ma))$')


@never_cache
def monitor(request, format=None):

    # For each check, a boolean pass/fail status to show in the template
    status_summary = {}
    results = {}

    checks = ['memcache', 'libraries', 'elastic', 'package_signer', 'path',
              'redis', 'receipt_signer', 'settings_check', 'solitude']

    for check in checks:
        with statsd.timer('monitor.%s' % check) as timer:
            status, result = getattr(monitors, check)()
        # state is a string. If it is empty, that means everything is fine.
        status_summary[check] = {'state': not status,
                                 'status': status}
        results['%s_results' % check] = result
        results['%s_timer' % check] = timer.ms

    # If anything broke, send HTTP 500.
    status_code = 200 if all(a['state']
                             for a in status_summary.values()) else 500

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


def handler403(request):
    if request.path_info.startswith('/api/'):
        # Pass over to handler403 view in api if api was targeted.
        return api.views.handler403(request)
    else:
        return jingo.render(request, 'amo/403.html', status=403)


def handler404(request):
    if request.path_info.startswith('/api/'):
        # Pass over to handler404 view in api if api was targeted.
        return api.views.handler404(request)
    else:
        return jingo.render(request, 'amo/404.html', status=404)


def handler500(request):
    if request.path_info.startswith('/api/'):
        # Pass over to handler500 view in api if api was targeted.
        return api.views.handler500(request)
    else:
        return jingo.render(request, 'amo/500.html', status=500)


def csrf_failure(request, reason=''):
    return jingo.render(request, 'amo/403.html',
                        {'because_csrf': 'CSRF' in reason},
                        status=403)


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
        # If possible, alter the PATH_INFO to contain the request of the page
        # the error occurred on, spec: http://mzl.la/P82R5y
        meta = request.META.copy()
        meta['PATH_INFO'] = v.get('document-uri', meta['PATH_INFO'])
        v = [(k, v[k]) for k in report if k in v]
        log_cef('CSP Violation', 5, meta, username=request.user,
                signature='CSPREPORT',
                msg='A client reported a CSP violation',
                cs6=v, cs6Label='ContentPolicy')
    except (KeyError, ValueError), e:
        log.debug('Exception in CSP report: %s' % e, exc_info=True)
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


@csrf_exempt
@post_required
def record(request):
    # The rate limiting is done up on the client, but if things go wrong
    # we can just turn the percentage down to zero.
    if get_collect_timings():
        return django_statsd_record(request)
    raise PermissionDenied


def plugin_check_redirect(request):
    return http.HttpResponseRedirect('%s?%s' %
            (settings.PFS_URL,
             iri_to_uri(request.META.get('QUERY_STRING', ''))))
