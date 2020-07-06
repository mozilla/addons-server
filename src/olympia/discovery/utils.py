import json
from collections import OrderedDict
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.utils.http import urlencode

import requests

from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo


log = olympia.core.logger.getLogger('z.amo')


def call_recommendation_server(server, client_id_or_guid, data, verb='get'):
    """Call taar `server` to get recommendations for a given
    `client_id_or_guid`.

    `data` is a dict containing either query parameters to be passed in the URL
    if we're calling the server through GET, or the data we'll pass through
    POST as json.
    The HTTP verb to use is either "get" or "post", controlled through `verb`,
    which defaults to "get"."""
    request_kwargs = {
        'timeout': settings.RECOMMENDATION_ENGINE_TIMEOUT
    }
    # Don't blindly trust client_id_or_guid, urljoin() will use its host name
    # and/or scheme if present.
    # https://docs.python.org/3/library/urllib.parse.html#urllib.parse.urljoin
    try:
        client_id_or_guid = urlsplit(client_id_or_guid).path
    except ValueError:
        client_id_or_guid = None
    if not client_id_or_guid or client_id_or_guid.startswith('/'):
        # That parameter was weird, don't call the recommendation server.
        return None
    if verb == 'get':
        params = OrderedDict(sorted(data.items(), key=lambda t: t[0]))
        endpoint = urljoin(server, '%s/%s%s' % (
            client_id_or_guid, '?' if params else '', urlencode(params)))

    else:
        endpoint = urljoin(server, '%s/' % client_id_or_guid)
        request_kwargs['json'] = data
    try:
        with statsd.timer('services.recommendations'):
            response = getattr(requests, verb)(endpoint, **request_kwargs)
        if response.status_code != 200:
            raise requests.exceptions.RequestException()
    except requests.exceptions.RequestException as e:
        log.exception('Calling recommendation engine failed: %s', e)
        statsd.incr('services.recommendations.fail')
        return None
    else:
        statsd.incr('services.recommendations.success')
    return json.loads(response.content).get('results', None)


def get_disco_recommendations(hashed_client_id, overrides):
    from olympia.addons.models import Addon
    from olympia.discovery.models import DiscoveryItem
    if overrides:
        data = {
            'options': {
                'promoted': [
                    [guid, 100 - i] for i, guid in enumerate(overrides)
                ]
            }
        }
    else:
        data = None
    guids = call_recommendation_server(
        settings.RECOMMENDATION_ENGINE_URL, hashed_client_id, data,
        verb='post')
    results = []
    if guids:
        qs = Addon.objects.select_related('discoveryitem').public().filter(
            guid__in=guids)
        for addon in qs:
            try:
                addon.discoveryitem
            except DiscoveryItem.DoesNotExist:
                # This just means the add-on isn't "known" as a possible
                # recommendation, but this is fine: create a dummy instance,
                # and it will use the add-on name and description to build the
                # data we need to return in the API.
                addon.discoveryitem = DiscoveryItem(addon=addon)
            results.append(addon.discoveryitem)
    return results


def replace_extensions(source, replacements):
    replacements = list(replacements)  # copy so we can pop it.
    return [replacements.pop(0)
            if item.addon.type == amo.ADDON_EXTENSION and replacements
            else item for item in source]
