import json

from django import http
from django.db import connection
from django.views.decorators.csrf import csrf_exempt

import jingo

from addons.models import Addon


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

    try:
        guids = json.loads(request.raw_post_data)
    except ValueError:
        return http.HttpResponseBadRequest()

    addon_ids = get_addon_ids(guids)


def get_addon_ids(guids):
    return Addon.objects.filter(guid__in=guids).values_list('id', flat=True)
