import json
import os
import sys
import time
from os import stat as os_stat

import django
from django import http
from django.conf import settings
from django.contrib.sitemaps.views import x_robots_tag
from django.core.exceptions import ViewDoesNotExist
from django.core.files.storage import default_storage as storage
from django.db.transaction import non_atomic_requests
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.utils.cache import patch_cache_control
from django.utils.http import http_date
from django.views.decorators.cache import never_cache

from django_statsd.clients import statsd
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

import olympia
from olympia import amo
from olympia.amo.utils import render, use_fake_fxa
from olympia.api.exceptions import base_500_data
from olympia.api.serializers import SiteStatusSerializer
from olympia.users.models import UserProfile

from . import monitors
from .sitemap import build_sitemap, get_sitemap_path


sitemap_log = olympia.core.logger.getLogger('z.monitor')


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
        status_summary[check] = {'state': not status, 'status': status}
        results['%s_results' % check] = result
        results['%s_timer' % check] = timer.ms

    # If anything broke, send HTTP 500.
    status_code = 200 if all(a['state'] for a in status_summary.values()) else 500

    return http.HttpResponse(json.dumps(status_summary), status=status_code)


@non_atomic_requests
def robots(request):
    """Generate a robots.txt"""
    _service = request.META['SERVER_NAME'] == settings.SERVICES_DOMAIN
    if _service or not settings.ENGAGE_ROBOTS:
        template = 'User-agent: *\nDisallow: /'
    else:
        ctx = {
            'apps': amo.APP_USAGE,
            'mozilla_user_id': settings.TASK_USER_ID,
            'mozilla_user_username': 'mozilla',
        }
        template = render(request, 'amo/robots.html', ctx)

    return HttpResponse(template, content_type='text/plain')


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
        return JsonResponse({'detail': str(NotFound.default_detail)}, status=404)
    return render(request, 'amo/404.html', status=404)


@non_atomic_requests
def handler500(request, **kwargs):
    if getattr(request, 'is_api', False):
        # API exceptions happening in DRF code would be handled with by our
        # custom_exception_handler function in olympia.api.exceptions, but in
        # the rare case where the exception is caused by a middleware or django
        # itself, it might not, so we need to handle it here.
        return HttpResponse(
            json.dumps(base_500_data()), content_type='application/json', status=500
        )
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
    return http.HttpResponse(
        '%s' % request.META['wsgi.loaded'], content_type='text/plain'
    )


@non_atomic_requests
def version(request):
    path = os.path.join(settings.ROOT, 'version.json')
    py_info = sys.version_info
    with open(path, 'r') as f:
        contents = json.loads(f.read())
    contents['python'] = '{major}.{minor}'.format(
        major=py_info.major, minor=py_info.minor
    )
    contents['django'] = '{major}.{minor}'.format(
        major=django.VERSION[0], minor=django.VERSION[1]
    )
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


# Special attribute that our <ModelBase>.get_absolute_url() looks for to
# determine whether it's a frontend view (that requires a different host prefix
# on admin instances) or not.
frontend_view.is_frontend_view = True


def fake_fxa_authorization(request):
    """Fake authentication page to bypass FxA in local development envs."""
    if not use_fake_fxa():
        raise Http404()
    interesting_accounts = UserProfile.objects.exclude(groups=None).exclude(
        deleted=True
    )[:25]
    return render(
        request,
        'amo/fake_fxa_authorization.html',
        {'interesting_accounts': interesting_accounts},
    )


class SiteStatusView(APIView):
    authentication_classes = []
    permission_classes = []

    @classmethod
    def as_view(cls, **initkwargs):
        return non_atomic_requests(super().as_view(**initkwargs))

    def get(self, request, format=None):
        return Response(SiteStatusSerializer(object()).data)


@non_atomic_requests
@x_robots_tag
def sitemap(request):
    expires_timestamp = None
    modified_timestamp = None

    section = request.GET.get('section')  # no section means the index page
    app = request.GET.get('app_name')
    page = request.GET.get('p', 1)
    if 'debug' in request.GET and settings.SITEMAP_DEBUG_AVAILABLE:
        content = build_sitemap(section, app, page)
        response = HttpResponse(content, content_type='application/xml')
    else:
        path = get_sitemap_path(section, app, page)
        try:
            content = storage.open(path)  # FileResponse closes files after consuming
            modified_timestamp = os_stat(path).st_mtime
        except FileNotFoundError as err:
            sitemap_log.exception(
                'Sitemap for section %s, page %s, not found',
                section,
                page,
                exc_info=err,
            )
            raise Http404
        expires_timestamp = modified_timestamp + (60 * 60 * 24)
        response = FileResponse(content, content_type='application/xml')
    if expires_timestamp:
        # check the expiry date wouldn't be in the past
        if expires_timestamp > time.time():
            response['Expires'] = http_date(expires_timestamp)
        else:
            # otherwise, just return a Cache-Control header of an hour
            patch_cache_control(response, max_age=60 * 60)
    if modified_timestamp:
        response['Last-Modified'] = http_date(modified_timestamp)
    return response
