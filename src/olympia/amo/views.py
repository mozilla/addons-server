import json
import os
import re

from django import http
from django.conf import settings
from django.db.transaction import non_atomic_requests
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache

from django_statsd.clients import statsd
from rest_framework.exceptions import NotFound

from olympia import amo, legacy_api
from olympia.amo.utils import render

from . import monitors


@never_cache
@non_atomic_requests
def monitor(request):
    # For each check, a boolean pass/fail status to show in the template
    status_summary = {}
    results = {}

    checks = ['memcache', 'libraries', 'elastic', 'path',
              'rabbitmq', 'redis', 'signer']

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

    return http.HttpResponse(json.dumps(status_summary), status=status_code)


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
    if re.match(settings.DRF_API_REGEX, request.path_info):
        return JsonResponse(
            {'detail': unicode(NotFound.default_detail)}, status=404)
    elif request.path_info.startswith('/api/'):
        # Pass over to handler404 view in api if api was targeted.
        return legacy_api.views.handler404(request)
    # X_IS_MOBILE_AGENTS is set by nginx as an env variable when it detects
    # a mobile User Agent or when the mamo cookie is present.
    if request.META.get('X_IS_MOBILE_AGENTS') == '1':
        return render(request, 'amo/404-responsive.html', status=404)
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
    from django.middleware.csrf import REASON_NO_REFERER, REASON_NO_CSRF_COOKIE
    ctx = {
        'reason': reason,
        'no_referer': reason == REASON_NO_REFERER,
        'no_cookie': reason == REASON_NO_CSRF_COOKIE,
    }
    return render(request, 'amo/403.html', ctx, status=403)


@non_atomic_requests
def loaded(request):
    return http.HttpResponse('%s' % request.META['wsgi.loaded'],
                             content_type='text/plain')


@non_atomic_requests
def version(request):
    path = os.path.join(settings.ROOT, 'version.json')
    return HttpResponse(open(path, 'rb'), content_type='application/json')
