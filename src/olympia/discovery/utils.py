import json

from django.conf import settings

import requests
from django_statsd.clients import statsd

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon

from . import data


log = olympia.core.logger.getLogger('z.amo')


def call_recommendation_server(telemetry_id):
    endpoint = settings.RECOMMENDATION_ENGINE_URL + telemetry_id
    log.debug(u'Calling recommendation server: {0}'.format(endpoint))
    try:
        with statsd.timer('services.recommendations'):
            response = requests.post(
                endpoint,
                timeout=settings.RECOMMENDATION_ENGINE_TIMEOUT)
        if response.status_code != 200:
            raise requests.exceptions.RequestException()
    except requests.exceptions.RequestException as e:
        msg = u'Calling recommendation engine failed: {0}'.format(e)
        log.error(msg)
        return []
    return json.loads(response.content).get('results', [])


def get_recommendations(telemetry_id):
    guids = call_recommendation_server(telemetry_id)
    ids = (Addon.objects.public().filter(guid__in=guids)
           .values_list('id', flat=True))
    return [data.DiscoItem(addon_id=id_, is_recommendation=True)
            for id_ in ids]


def replace_extensions(source, replacements):
    replacements = list(replacements)  # copy so we can pop it.
    return [replacements.pop(0)
            if item.type == amo.ADDON_EXTENSION and replacements else item
            for item in source]
