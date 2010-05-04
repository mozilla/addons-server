import json

from django import http
from django.views.decorators.csrf import csrf_exempt

import jingo

from addons.models import Addon
from bandwagon.models import Collection, SyncedCollection


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


def get_synced_collection(addon_ids, token):
    """
    Get a synced collection for these addons. May reuse an existing collection.

    The token is associated with the collection.
    """
    index = Collection.make_index(addon_ids)
    try:
        c = (SyncedCollection.objects.no_cache()
             .filter(addon_index=index))[0]
    except IndexError:
        c = SyncedCollection.objects.create(listed=False)
        c.set_addons(addon_ids)

    c.token_set.create(token=token)
    return c
