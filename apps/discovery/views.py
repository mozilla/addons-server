import json
import uuid

from django import http
from django.views.decorators.csrf import csrf_exempt

import jingo

import amo.utils
import api.utils
from addons.models import Addon
from bandwagon.models import Collection, SyncedCollection, CollectionToken


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
    token = get_random_token()
    synced = get_synced_collection(addon_ids, token)
    recs = synced.get_recommendations()
    ids = list(recs.addons.order_by('collectionaddon__ordering')
               .values_list('id', flat=True))[:limit]
    data = {'token': token, 'recommendations': recs.get_url_path(),
            'addons': [api.utils.addon_to_dict(Addon.objects.get(pk=pk))
                       for pk in ids]}
    content = json.dumps(data, cls=amo.utils.JSONEncoder)
    return http.HttpResponse(content, content_type='application/json')


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


def get_random_token():
    """Get a random token for the user, make sure it's unique."""
    while 1:
        token = unicode(uuid.uuid4())
        if CollectionToken.objects.filter(token=token).count() == 0:
            return token
