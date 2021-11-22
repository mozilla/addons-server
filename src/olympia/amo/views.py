import json
import os
import sys

import django
from django import http
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.sitemaps.views import x_robots_tag
from django.core.exceptions import PermissionDenied, ViewDoesNotExist
from django.core.paginator import EmptyPage, PageNotAnInteger
from django.db.transaction import non_atomic_requests
from django.http import Http404, HttpResponse, JsonResponse
from django.template.response import TemplateResponse
from django.utils.cache import patch_cache_control
from django.views.decorators.cache import never_cache

from django_statsd.clients import statsd
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

import olympia
from olympia import amo
from olympia.amo.utils import HttpResponseXSendFile, use_fake_fxa
from olympia.api.exceptions import base_500_data
from olympia.api.serializers import SiteStatusSerializer
from olympia.users.models import UserProfile

from . import monitors
from .sitemap import get_sitemap_path, get_sitemaps, render_index_xml


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


@never_cache
@non_atomic_requests
def client_info(request):
    if getattr(settings, 'ENV', None) != 'dev':
        raise PermissionDenied
    keys = (
        'HTTP_USER_AGENT',
        'HTTP_X_COUNTRY_CODE',
        'HTTP_X_FORWARDED_FOR',
        'REMOTE_ADDR',
    )
    data = {key: request.META.get(key) for key in keys}
    return JsonResponse(data)


@non_atomic_requests
def robots(request):
    """Generate a robots.txt"""
    _service = request.META['SERVER_NAME'] == settings.SERVICES_DOMAIN
    if _service or not settings.ENGAGE_ROBOTS:
        response = HttpResponse('User-agent: *\nDisallow: /', content_type='text/plain')
    else:
        ctx = {
            'apps': amo.APP_USAGE,
            'mozilla_user_id': settings.TASK_USER_ID,
            'mozilla_user_username': 'mozilla',
        }
        response = TemplateResponse(request, 'amo/robots.html', context=ctx, content_type='text/plain')

    return response


@non_atomic_requests
def contribute(request):
    path = os.path.join(settings.ROOT, 'contribute.json')
    return HttpResponse(open(path, 'rb'), content_type='application/json')


@non_atomic_requests
def handler403(request, exception=None, **kwargs):
    return TemplateResponse(request, 'amo/403.html', status=403)


@non_atomic_requests
def handler404(request, exception=None, **kwargs):
    if getattr(request, 'is_api', False):
        # It's a v3+ api request
        return JsonResponse({'detail': str(NotFound.default_detail)}, status=404)
    return TemplateResponse(request, 'amo/404.html', status=404)


@non_atomic_requests
def handler500(request, **kwargs):
    # To avoid database queries, the handler500() cannot evaluate the user - so
    # we need to avoid making log calls (our custom adapter would fetch the
    # user from the current thread) and set request.user to anonymous to avoid
    # its usage in context processors.
    request.user = AnonymousUser()
    if getattr(request, 'is_api', False):
        # API exceptions happening in DRF code would be handled with by our
        # custom_exception_handler function in olympia.api.exceptions, but in
        # the rare case where the exception is caused by a middleware or django
        # itself, it might not, so we need to handle it here.
        return HttpResponse(
            json.dumps(base_500_data()), content_type='application/json', status=500
        )
    return TemplateResponse(request, 'amo/500.html', status=500)


@non_atomic_requests
def csrf_failure(request, reason=''):
    from django.middleware.csrf import REASON_NO_REFERER, REASON_NO_CSRF_COOKIE

    ctx = {
        'reason': reason,
        'no_referer': reason == REASON_NO_REFERER,
        'no_cookie': reason == REASON_NO_CSRF_COOKIE,
    }
    return TemplateResponse(request, 'amo/403.html', context=ctx, status=403)


@non_atomic_requests
def loaded(request):
    return http.HttpResponse(
        '%s' % request.META['wsgi.loaded'], content_type='text/plain'
    )


@non_atomic_requests
def version(request):
    path = os.path.join(settings.ROOT, 'version.json')
    with open(path) as f:
        contents = json.loads(f.read())

    py_info = sys.version_info
    contents['python'] = '{major}.{minor}'.format(
        major=py_info.major, minor=py_info.minor
    )
    contents['django'] = '{major}.{minor}'.format(
        major=django.VERSION[0], minor=django.VERSION[1]
    )

    path = os.path.join(settings.ROOT, 'package.json')
    with open(path) as f:
        data = json.loads(f.read())
        contents['addons-linter'] = data['dependencies']['addons-linter']

    res = HttpResponse(json.dumps(contents), content_type='application/json')
    res.headers['Access-Control-Allow-Origin'] = '*'
    return res


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
    return TemplateResponse(
        request,
        'amo/fake_fxa_authorization.html',
        context={'interesting_accounts': interesting_accounts},
    )


class SiteStatusView(APIView):
    authentication_classes = []
    permission_classes = []

    @classmethod
    def as_view(cls, **initkwargs):
        return non_atomic_requests(super().as_view(**initkwargs))

    def get(self, request, format=None):
        return Response(SiteStatusSerializer(object()).data)


class InvalidSection(Exception):
    pass


@non_atomic_requests
@x_robots_tag
def sitemap(request):
    section = request.GET.get('section')  # no section means the index page
    app = request.GET.get('app_name')
    page = request.GET.get('p', 1)
    if 'debug' in request.GET and settings.SITEMAP_DEBUG_AVAILABLE:
        try:
            sitemaps = get_sitemaps()
            if not section:
                if page != 1:
                    raise EmptyPage
                content = render_index_xml(sitemaps)
            else:
                sitemap_object = sitemaps.get((section, amo.APPS.get(app)))
                if not sitemap_object:
                    raise InvalidSection
                content = sitemap_object.render(app, page)
        except EmptyPage:
            raise Http404('Page %s empty' % page)
        except PageNotAnInteger:
            raise Http404('No page "%s"' % page)
        except InvalidSection:
            raise Http404('No sitemap available for section: %r' % section)
        response = HttpResponse(content, content_type='application/xml')
    else:
        path = get_sitemap_path(section, app, page)
        response = HttpResponseXSendFile(request, path, content_type='application/xml')
        patch_cache_control(response, max_age=60 * 60)
    return response
