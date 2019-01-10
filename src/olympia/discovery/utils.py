import json
from collections import OrderedDict
from six.moves.urllib_parse import urljoin

from django.conf import settings
from django.utils.http import urlencode

import requests

from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo


log = olympia.core.logger.getLogger('z.amo')


def call_recommendation_server(id_or_guid, params, server):
    params = OrderedDict(sorted(params.items(), key=lambda t: t[0]))
    endpoint = urljoin(
        server,
        '%s/%s%s' % (id_or_guid, '?' if params else '', urlencode(params)))
    log.debug(u'Calling recommendation server: {0}'.format(endpoint))
    try:
        with statsd.timer('services.recommendations'):
            response = getattr(requests, verb)(endpoint, **request_kwargs)
        if response.status_code != 200:
            raise requests.exceptions.RequestException()
    except requests.exceptions.RequestException as e:
        log.error(u'Calling recommendation engine failed: {0}'.format(e))
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
