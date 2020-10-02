from urllib.parse import urlparse

from django.conf import settings

import requests
from django_statsd.clients import statsd

import olympia.core.logger


log = olympia.core.logger.getLogger('z.shelves')


def call_adzerk_server(placeholders):
    """Call adzerk server to get sponsored addon results.

    `placeholders` is a list of arbitrary strings that we pass so we can
    identify the order of the results in the response dict."""
    site_id = settings.ADZERK_SITE_ID
    network_id = settings.ADZERK_NETWORK_ID
    placements = [
        {"divName": ph,
         "networkId": network_id,
         "siteId": site_id,
         "adTypes": [5]} for ph in placeholders]

    try:
        log.info('Calling adzerk')
        with statsd.timer('services.adzerk'):
            response = requests.post(
                settings.ADZERK_URL,
                json={'placements': placements},
                timeout=settings.ADZERK_TIMEOUT)
        if response.status_code != 200:
            raise requests.exceptions.RequestException()
    except requests.exceptions.RequestException as e:
        log.exception('Calling adzerk failed: %s', e)
        statsd.incr('services.adzerk.fail')
        return None
    else:
        statsd.incr('services.adzerk.success')
    try:
        return response.json()
    except ValueError:
        return {}


def process_adzerk_result(decision):
    contents = (decision.get('contents') or [{}])[0]
    return {
        'impression': urlparse(decision.get('impressionUrl', '')).query,
        'click': urlparse(decision.get('clickUrl', '')).query,
        'addon_id':
            contents.get('data', {}).get('customData', {}).get('id', None)
    }
    return


def process_adzerk_results(response, placeholders):
    response_decisions = response.get('decisions', {})
    decisions = [response_decisions.get(ph, {}) for ph in placeholders]
    results_dict = {}
    for decision in decisions:
        result = process_adzerk_result(decision)
        addon_id = str(result['addon_id'])
        if addon_id in results_dict or not addon_id.isdigit():
            continue  # no duplicates or weird/missing ids
        results_dict[addon_id] = result
    return results_dict


def get_addons_from_adzerk(count):
    placeholders = [f'div{i}' for i in range(count)]
    response = call_adzerk_server(placeholders)
    results_dict = (
        process_adzerk_results(response, placeholders) if response else {})
    log.debug(f'{results_dict=}')
    # results_dict['16'] = list(results_dict.values())[0]  # TESTING HACK
    return results_dict
