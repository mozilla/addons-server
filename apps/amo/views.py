import json

from django import http
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

import commonware.log
import jingo
import waffle
from django_arecibo.tasks import post
from statsd import statsd

import amo
import api
import files.tasks
from amo.decorators import no_login_required, post_required
from amo.utils import log_cef
from . import monitors

log = commonware.log.getLogger('z.amo')
monitor_log = commonware.log.getLogger('z.monitor')
jp_log = commonware.log.getLogger('z.jp.repack')


@never_cache
@no_login_required
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


def handler404(request):
    webapp = settings.APP_PREVIEW
    template = 'amo/404%s.html' % ('_apps' if webapp else '')
    if request.path_info.startswith('/api/'):
        # Pass over to handler404 view in api if api was targeted
        return api.views.handler404(request)
    else:
        return jingo.render(request, template, {'webapp': webapp}, status=404)


def handler500(request):
    webapp = settings.APP_PREVIEW
    template = 'amo/500%s.html' % ('_apps' if webapp else '')
    arecibo = getattr(settings, 'ARECIBO_SERVER_URL', '')
    if arecibo:
        post(request, 500)
    if request.path_info.startswith('/api/'):
        return api.views.handler500(request)
    else:
        return jingo.render(request, template, {'webapp': webapp}, status=500)


def csrf_failure(request, reason=''):
    webapp = settings.APP_PREVIEW
    template = 'amo/403%s.html' % ('_apps' if webapp else '')
    return jingo.render(request, template,
                        {'csrf': 'CSRF' in reason, 'webapp': webapp},
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
        # CEF module wants a dictionary of environ, we want request
        # to be the page with error on it, that's contained in the csp-report
        # so we need to modify the meta before we pass in to the logger
        meta = request.META.copy()
        method, url = v['request'].split(' ', 1)
        meta.update({'REQUEST_METHOD': method, 'PATH_INFO': url})
        v = [(k, v[k]) for k in report if k in v]
        log_cef('CSP Violation', 5, meta, username=request.user,
                signature='CSPREPORT',
                msg='A client reported a CSP violation',
                cs7=v, cs7Label='ContentPolicy')
    except Exception, e:
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


def graphite(request, site):
    ctx = {'width': 586, 'height': 308}
    ctx.update(request.GET.items())
    ctx['site'] = site
    return jingo.render(request, 'services/graphite.html', ctx)
