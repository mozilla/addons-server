import json
import urlparse
from collections import OrderedDict

from django.conf import settings
from django.utils.http import urlencode

import requests

from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo

from . import data


log = olympia.core.logger.getLogger('z.amo')


def call_recommendation_server(id_or_guid, params, server):
    params = OrderedDict(sorted(params.items(), key=lambda t: t[0]))
    endpoint = urlparse.urljoin(
        server,
        '%s/%s%s' % (id_or_guid, '?' if params else '', urlencode(params)))
    log.debug(u'Calling recommendation server: {0}'.format(endpoint))
    try:
        with statsd.timer('services.recommendations'):
            response = requests.get(
                endpoint,
                timeout=settings.RECOMMENDATION_ENGINE_TIMEOUT)
        if response.status_code != 200:
            raise requests.exceptions.RequestException()
    except requests.exceptions.RequestException as e:
        log.error(u'Calling recommendation engine failed: {0}'.format(e))
        statsd.incr('services.recommendations.fail')
        return []
    else:
        statsd.incr('services.recommendations.success')
    return json.loads(response.content).get('results', [])


def get_recommendations(telemetry_id, params):
    from olympia.addons.models import Addon  # circular import
    guids = call_recommendation_server(
        telemetry_id, params, settings.RECOMMENDATION_ENGINE_URL)
    ids = (Addon.objects.public().filter(guid__in=guids)
           .values_list('id', flat=True))
    return [data.DiscoItem(addon_id=id_, is_recommendation=True)
            for id_ in ids]


def replace_extensions(source, replacements):
    replacements = list(replacements)  # copy so we can pop it.
    return [replacements.pop(0)
            if item.type == amo.ADDON_EXTENSION and replacements else item
            for item in source]
