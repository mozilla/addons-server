import json
import os
import sys

import django
from django import http
from django.conf import settings
from django.core.exceptions import ViewDoesNotExist
from django.db.transaction import non_atomic_requests
from django.http import HttpResponse, JsonResponse
from django.views.decorators.cache import never_cache

from django_statsd.clients import statsd
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from olympia import amo
from olympia.amo.utils import render
from olympia.api.exceptions import base_500_data
from olympia.api.serializers import SiteStatusSerializer

from . import monitors


@never_cache
@non_atomic_requests
def monitor(request):
    # For each check, a boolean pass/fail status to show in the template
    status_summary = {}
    results = {}

    checks = ['memcache', 'libraries', 'elastic', 'path', 'rabbitmq', 'signer']

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
        ctx = {
            'apps': amo.APP_USAGE,
            'mozilla_user_id': settings.TASK_USER_ID,
        }
        template = render(request, 'amo/robots.html', ctx)

    return HttpResponse(template, content_type="text/plain")


@non_atomic_requests
def contribute(request):
    path = os.path.join(settings.ROOT, 'contribute.json')
    return HttpResponse(open(path, 'rb'), content_type='application/json')


@non_atomic_requests
def handler403(request, exception=None, **kwargs):
    return render(request, 'amo/403.html', status=403)


@non_atomic_requests
def handler404(request, exception=None, **kwargs):
    if getattr(request, 'is_api', False):
        # It's a v3+ api request
        return JsonResponse(
            {'detail': str(NotFound.default_detail)}, status=404)
    # X_IS_MOBILE_AGENTS is set by nginx as an env variable when it detects
    # a mobile User Agent or when the mamo cookie is present.
    if request.META.get('X_IS_MOBILE_AGENTS') == '1':
        return render(request, 'amo/404-responsive.html', status=404)
    else:
        return render(request, 'amo/404.html', status=404)


@non_atomic_requests
def handler500(request, **kwargs):
    if getattr(request, 'is_api', False):
        # API exceptions happening in DRF code would be handled with by our
        # custom_exception_handler function in olympia.api.exceptions, but in
        # the rare case where the exception is caused by a middleware or django
        # itself, it might not, so we need to handle it here.
        return HttpResponse(
            json.dumps(base_500_data()),
            content_type='application/json',
            status=500)
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
    py_info = sys.version_info
    with open(path, 'r') as f:
        contents = json.loads(f.read())
    contents['python'] = '{major}.{minor}'.format(
        major=py_info.major, minor=py_info.minor)
    contents['django'] = '{major}.{minor}'.format(
        major=django.VERSION[0], minor=django.VERSION[1])
    return HttpResponse(json.dumps(contents), content_type='application/json')


def _frontend_view(*args, **kwargs):
    """View has migrated to addons-frontend but we still have the url so we
    can reverse() to it in addons-server code.
    If you ever hit this url somethunk gun wrong!"""
    raise ViewDoesNotExist()


@non_atomic_requests
def frontend_view(*args, **kwargs):
    """Wrap _frontend_view so we can mock it in tests."""
    return _frontend_view(*args, **kwargs)


class SiteStatusView(APIView):
    authentication_classes = []
    permission_classes = []

    @classmethod
    def as_view(cls, **initkwargs):
        return non_atomic_requests(super().as_view(**initkwargs))

    def get(self, request, format=None):
        return Response(SiteStatusSerializer(object()).data)
