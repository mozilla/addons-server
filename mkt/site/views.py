import json

from django.http import HttpResponse, HttpResponseForbidden
from django.template import RequestContext
from django.views.decorators.csrf import csrf_exempt

from django_statsd.views import record as django_statsd_record
import jingo
from session_csrf import anonymous_csrf, anonymous_csrf_exempt

from amo.context_processors import get_collect_timings
from amo.decorators import post_required
from amo.helpers import media
import api.views


def handler404(request):
    if request.path_info.startswith('/api/'):
        # Pass over to API handler404 view if API was targeted.
        return api.views.handler404(request)
    else:
        return jingo.render(request, 'site/404.html', status=404)


def handler500(request):
    if request.path_info.startswith('/api/'):
        return api.views.handler500(request)
    else:
        return jingo.render(request, 'site/500.html', status=500)


def csrf_failure(request, reason=''):
    return jingo.render(request, 'site/403.html',
                        {'because_csrf': 'CSRF' in reason}, status=403)


def manifest(request):
    ctx = RequestContext(request)
    data = {
        'name': 'Mozilla Marketplace',
        'description': 'The Mozilla Marketplace',
        'developer': {
            'name': 'Mozilla',
            'url': 'http://mozilla.org',
        },
        'icons': {
            # Using the default addon image until we get a marketplace logo.
            '32': media(ctx, 'img/mkt/logos/32.png'),
            '64': media(ctx, 'img/mkt/logos/64.png'),
            '128': media(ctx, 'img/mkt/logos/128.png'),
        },
        # TODO: when we have specific locales, add them in here.
        'locales': {},
        'default_locale': 'en-US'
    }
    return HttpResponse(json.dumps(data),
                        mimetype='application/x-web-app-manifest+json')


def robots(request):
    """Generate a robots.txt"""
    template = jingo.render(request, 'site/robots.txt')
    return HttpResponse(template, mimetype="text/plain")


@anonymous_csrf
@anonymous_csrf_exempt
@post_required
def csrf(request):
    """A CSRF for anonymous users only."""
    if not request.amo_user:
        data = json.dumps({'csrf': RequestContext(request)['csrf_token']})
        return HttpResponse(data, content_type='application/json')

    return HttpResponseForbidden()


@csrf_exempt
@post_required
def record(request):
    # The rate limiting is done up on the client, but if things go wrong
    # we can just turn the percentage down to zero.
    if get_collect_timings():
        print request.POST
        return django_statsd_record(request)
    return http.HttpResponseForbidden()
