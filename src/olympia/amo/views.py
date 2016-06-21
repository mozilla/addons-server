import json
import os
import re

from django import http
from django.conf import settings
from django.db.transaction import non_atomic_requests
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache

import commonware.log
from django_statsd.clients import statsd

from olympia import amo, legacy_api

from . import monitors

log = commonware.log.getLogger('z.amo')
monitor_log = commonware.log.getLogger('z.monitor')
jp_log = commonware.log.getLogger('z.jp.repack')


flash_re = re.compile(r'^(Win|(PPC|Intel) Mac OS X|Linux.+i\d86)|SunOs',
                      re.IGNORECASE)
quicktime_re = re.compile(
    r'^(application/(sdp|x-(mpeg|rtsp|sdp))|audio/(3gpp(2)?|AMR|aiff|basic|'
    r'mid(i)?|mp4|mpeg|vnd\.qcelp|wav|x-(aiff|m4(a|b|p)|midi|mpeg|wav))|'
    r'image/(pict|png|tiff|x-(macpaint|pict|png|quicktime|sgi|targa|tiff))|'
    r'video/(3gpp(2)?|flc|mp4|mpeg|quicktime|sd-video|x-mpeg))$')
java_re = re.compile(
    r'^application/x-java-((applet|bean)(;jpi-version=1\.5|;'
    r'version=(1\.(1(\.[1-3])?|(2|4)(\.[1-2])?|3(\.1)?|5)))?|vm)$')
wmp_re = re.compile(
    r'^(application/(asx|x-(mplayer2|ms-wmp))|video/x-ms-(asf(-plugin)?|'
    r'wm(p|v|x)?|wvx)|audio/x-ms-w(ax|ma))$')


@never_cache
@non_atomic_requests
def monitor(request, format=None):

    # For each check, a boolean pass/fail status to show in the template
    status_summary = {}
    results = {}

    checks = ['memcache', 'libraries', 'elastic', 'path',
              'rabbitmq', 'redis']

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

    return render(request, 'services/monitor.html', ctx, status=status_code)


@non_atomic_requests
def robots(request):
    """Generate a robots.txt"""
    _service = (request.META['SERVER_NAME'] == settings.SERVICES_DOMAIN)
    if _service or not settings.ENGAGE_ROBOTS:
        template = "User-agent: *\nDisallow: /"
    else:
        template = render(request, 'amo/robots.html', {'apps': amo.APP_USAGE})

    return HttpResponse(template, content_type="text/plain")


@non_atomic_requests
def contribute(request):
    path = os.path.join(settings.ROOT, 'contribute.json')
    return HttpResponse(open(path, 'rb'), content_type='application/json')


@non_atomic_requests
def handler403(request):
    if request.path_info.startswith('/api/'):
        # Pass over to handler403 view in api if api was targeted.
        return legacy_api.views.handler403(request)
    else:
        return render(request, 'amo/403.html', status=403)


@non_atomic_requests
def handler404(request):
    if request.path_info.startswith('/api/'):
        # Pass over to handler404 view in api if api was targeted.
        return legacy_api.views.handler404(request)
    else:
        return render(request, 'amo/404.html', status=404)


@non_atomic_requests
def handler500(request):
    if request.path_info.startswith('/api/'):
        # Pass over to handler500 view in api if api was targeted.
        return legacy_api.views.handler500(request)
    else:
        return render(request, 'amo/500.html', status=500)


@non_atomic_requests
def csrf_failure(request, reason=''):
    return render(request, 'amo/403.html',
                  {'because_csrf': 'CSRF' in reason}, status=403)


@non_atomic_requests
def loaded(request):
    return http.HttpResponse('%s' % request.META['wsgi.loaded'],
                             content_type='text/plain')


@non_atomic_requests
def version(request):
    path = os.path.join(settings.ROOT, 'version.json')
    return HttpResponse(open(path, 'rb'), content_type='application/json')
