from django.http import HttpResponse

import jingo

from amo.decorators import no_login_required
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
def robots(request):
    """Generate a robots.txt"""
    template = jingo.render(request, 'site/robots.txt')
    return HttpResponse(template, mimetype="text/plain")
