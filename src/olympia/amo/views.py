import json
import os
import re
import time

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.sitemaps.views import x_robots_tag
from django.core.exceptions import PermissionDenied, ViewDoesNotExist
from django.core.paginator import EmptyPage, PageNotAnInteger
from django.db.transaction import non_atomic_requests
from django.http import Http404, HttpResponse, HttpResponseNotFound, JsonResponse
from django.template.response import TemplateResponse
from django.utils.cache import patch_cache_control
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from rest_framework import exceptions as drf_exceptions
from rest_framework.response import Response
from rest_framework.views import APIView

from olympia import amo
from olympia.accounts.utils import get_fxa_config
from olympia.amo.utils import HttpResponseXSendFile, use_fake_fxa
from olympia.api.exceptions import base_500_data
from olympia.api.serializers import SiteStatusSerializer
from olympia.core.utils import get_version_json
from olympia.users.models import UserProfile

from . import monitors
from .sitemap import InvalidSection, get_sitemap_path, get_sitemaps, render_index_xml


def _exec_monitors(checks: list[str]):
    status_summary = monitors.execute_checks(checks)
    status_code = 200 if all(a['state'] for a in status_summary.values()) else 500
    return JsonResponse(status_summary, status=status_code)


MONITORS = {
    'internal': [
        'memcache',
        'libraries',
        'elastic',
        'path',
        'database',
    ],
    'external': [
        'rabbitmq',
        'signer',
        'remotesettings',
        'cinder',
    ],
}


@never_cache
@non_atomic_requests
def front_heartbeat(request):
    """Check internal monitors only."""
    return _exec_monitors(MONITORS['internal'])


@never_cache
@non_atomic_requests
def services_monitor(request):
    """Check all monitors."""
    return _exec_monitors(
        [
            *MONITORS['internal'],
            *MONITORS['external'],
            'dummy_monitor',
        ]
    )


@csrf_exempt
@non_atomic_requests
def dummy_upload(request):
    if getattr(settings, 'ENV', None) == 'prod':
        raise PermissionDenied
    # dd if=/dev/urandom of=/tmp/test.img bs=100M count=1
    # curl -F parse=1 -F upload=@/tmp/test.img <host>/services/dummy_upload
    if request.POST.get('parse') and 'upload' in request.FILES:
        buf = request.FILES['upload'].read()
    else:
        buf = ''

    return JsonResponse(
        {
            # request._start_time is set by GraphiteRequestTimingMiddleware
            'elapsed_in_app': int((time.time() - request._start_time) * 1000),
            'buf_size': len(buf),
        }
    )


@never_cache
@csrf_exempt
@non_atomic_requests
def client_info(request):
    if getattr(settings, 'ENV', None) != 'dev':
        raise PermissionDenied
    keys = (
        'HTTP_USER_AGENT',
        'HTTP_X_COUNTRY_CODE',
        'HTTP_X_FORWARDED_FOR',
        'REMOTE_ADDR',
        'SERVER_NAME',
    )
    data = {key: request.META.get(key) for key in keys}
    data['POST'] = request.POST
    data['GET'] = request.GET
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
        response = TemplateResponse(
            request, 'amo/robots.html', context=ctx, content_type='text/plain'
        )

    return response


@non_atomic_requests
def contribute(request):
    path = os.path.join(settings.ROOT, 'contribute.json')
    return HttpResponse(open(path, 'rb'), content_type='application/json')


@non_atomic_requests
def handler403(request, exception=None, **kwargs):
    if getattr(request, 'is_api', False):
        return JsonResponse(
            {'detail': str(drf_exceptions.PermissionDenied.default_detail)}, status=403
        )
    return TemplateResponse(request, 'amo/403.html', status=403)


@non_atomic_requests
def handler404(request, exception=None, **kwargs):
    if getattr(request, 'is_api', False):
        # It's a v3+ api request (/api/vX/ or /api/auth/)
        return JsonResponse(
            {'detail': str(drf_exceptions.NotFound.default_detail)}, status=404
        )
    elif re.match(r'^/api/\d\.\d/', getattr(request, 'path_info', '')):
        # It's a legacy API request in the form of /api/X.Y/. We use path_info,
        # which is set in LocaleAndAppURLMiddleware, because there might be a
        # locale and app prefix we don't care about in the URL.
        response = HttpResponseNotFound()
        patch_cache_control(response, max_age=60 * 60 * 48)
        return response
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
        return JsonResponse(base_500_data(), status=500)
    return TemplateResponse(request, 'amo/500.html', status=500)


@non_atomic_requests
def csrf_failure(request, reason=''):
    from django.middleware.csrf import REASON_NO_CSRF_COOKIE, REASON_NO_REFERER

    ctx = {
        'reason': reason,
        'no_referer': reason == REASON_NO_REFERER,
        'no_cookie': reason == REASON_NO_CSRF_COOKIE,
    }
    return TemplateResponse(request, 'amo/403.html', context=ctx, status=403)


@non_atomic_requests
def version(request):
    contents = get_version_json()

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
    if not use_fake_fxa(get_fxa_config(request)):
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


@non_atomic_requests
@x_robots_tag
def sitemap(request):
    section = request.GET.get('section')  # no section means the index page
    app = request.GET.get('app_name')
    page = request.GET.get('p', 1)
    try:
        if 'debug' in request.GET and settings.SITEMAP_DEBUG_AVAILABLE:
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
            response = HttpResponse(content, content_type='application/xml')

        else:
            path = get_sitemap_path(section, app, page)
            response = HttpResponseXSendFile(
                request, path, content_type='application/xml'
            )
            patch_cache_control(response, max_age=60 * 60)

    except EmptyPage as exc:
        raise Http404('Page %s empty' % page) from exc
    except PageNotAnInteger as exc:
        raise Http404('No page "%s"' % page) from exc
    except InvalidSection as exc:
        raise Http404('No sitemap available for section: %r' % section) from exc

    return response
