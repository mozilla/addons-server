from django import http
from django.views.decorators.csrf import csrf_exempt

import jingo


def pane(request, version, os):
    return jingo.render(request, 'discovery/pane.html')


@csrf_exempt
def recommendations(request, limit=5):
    """
    Figure out recommended add-ons for an anonymous user based on POSTed guids.

    POST body looks like {"guids": [...]} with an optional "token" key if
    they've been here before.
    """
    if request.method != 'POST':
        return http.HttpResponseNotAllowed(['POST'])
