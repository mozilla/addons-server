import json

from django.http import HttpResponse
from django.template import RequestContext

import jingo

from amo.decorators import no_login_required
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
    return jingo.render(request, 'site/403.html', {'csrf': 'CSRF' in reason},
                        status=403)


@no_login_required
def manifest(request):
    data = {
        'name': 'Mozilla Marketplace',
        'description': 'The Mozilla Marketplace',
        'developer': {
            'name': 'Mozilla',
            'url': 'http://mozilla.org',
        },
        'icons': {
            # Using the default addon image until we get a marketplace logo.
            '32': media(RequestContext(request),
                        'img/zamboni/default-addon.png'),
        },
        # TODO: when we have specific locales, add them in here.
        'locales': {},
        'default_locale': 'en-US'
    }
    return HttpResponse(json.dumps(data),
                        mimetype='application/x-web-app-manifest+json')


@no_login_required
def robots(request):
    """Generate a robots.txt"""
    template = jingo.render(request, 'site/robots.txt')
    return HttpResponse(template, mimetype="text/plain")
