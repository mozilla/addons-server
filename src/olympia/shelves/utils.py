from urllib.parse import quote, unquote, urlsplit, urlunsplit

from django.conf import settings
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner

import requests
from django_statsd.clients import statsd
from rest_framework.exceptions import APIException

import olympia.core.logger


log = olympia.core.logger.getLogger('z.shelves')


def call_adzerk_server(url, json_data=None):
    """Call adzerk server to get sponsored addon results."""
    json_response = {}
    try:
        log.info('Calling adzerk')
        with statsd.timer('services.adzerk'):
            response = requests.post(
                url,
                json=json_data,
                timeout=settings.ADZERK_TIMEOUT)
        if response.status_code != 200:
            raise requests.exceptions.RequestException()
        json_response = response.json()
    except requests.exceptions.RequestException as e:
        log.exception('Calling adzerk failed: %s', e)
        statsd.incr('services.adzerk.fail')
    except ValueError as e:
        log.exception('Decoding adzerk response failed: %s', e)
        statsd.incr('services.adzerk.fail')
    else:
        statsd.incr('services.adzerk.success')
    return json_response


def ping_adzerk_server(url, type='impression'):
    """Ping adzerk server for impression/clicks"""
    try:
        log.info('Calling adzerk')
        with statsd.timer('services.adzerk'):
            response = requests.get(
                url,
                timeout=settings.ADZERK_TIMEOUT)
        if response.status_code != 200:
            raise requests.exceptions.RequestException()
    except requests.exceptions.RequestException as e:
        log.exception('Calling adzerk failed: %s', e)
        statsd.incr(f'services.adzerk.{type}.fail')
    else:
        statsd.incr(f'services.adzerk.{type}.success')


def path_and_query(url, extra_query_params=()):
    split = urlsplit(url)
    query = '&'.join((split.query, *extra_query_params))
    return quote(urlunsplit(('', '', split.path.lstrip('/'), query, '')))


def process_adzerk_result(decision):
    contents = (decision.get('contents') or [{}])[0]
    events = (decision.get('events') or [{}])[0]
    addon_id = str(contents.get('data', {}).get('customData', {}).get('id'))
    return addon_id, {
        'impression': path_and_query(decision.get('impressionUrl', '')),
        'click': path_and_query(decision.get('clickUrl', ''), ('noredirect',)),
        'conversion': path_and_query(events.get('url', '')),
    }


def process_adzerk_results(response, placeholders):
    response_decisions = response.get('decisions', {})
    decisions = [(response_decisions.get(ph) or {}) for ph in placeholders]
    results_dict = {}
    for decision in decisions:
        addon_id, result = process_adzerk_result(decision)
        if addon_id in results_dict or not addon_id.isdigit():
            continue  # no duplicates or weird/missing ids
        results_dict[addon_id] = result
    return results_dict


def get_addons_from_adzerk(count):
    placeholders = [f'div{i}' for i in range(count)]
    site_id = settings.ADZERK_SITE_ID
    network_id = settings.ADZERK_NETWORK_ID
    placements = [
        {
            "divName": ph,
            "networkId": network_id,
            "siteId": site_id,
            "adTypes": [5],
            "eventIds": [2],
        } for ph in placeholders]
    url = settings.ADZERK_URL
    response = call_adzerk_server(url, {'placements': placements})
    results_dict = (
        process_adzerk_results(response, placeholders) if response else {})
    return results_dict


def send_impression_pings(signed_impressions):
    impressions = unsign_signed_blob(
        signed_impressions,
        settings.ADZERK_IMPRESSION_TIMEOUT).split(',')
    base_url = settings.ADZERK_EVENT_URL
    urls = [f'{base_url}{unquote(impression)}' for impression in impressions]
    for url in urls:
        ping_adzerk_server(url, type='impression')


def send_event_ping(signed_event, type):
    event = unsign_signed_blob(
        signed_event,
        settings.ADZERK_EVENT_TIMEOUT)
    base_url = settings.ADZERK_EVENT_URL
    url = f'{base_url}{unquote(event)}'
    ping_adzerk_server(url, type=type)


def filter_adzerk_results_to_es_results_qs(results, es_results_qs):
    results_ids = [str(hit.id) for hit in es_results_qs]
    extra_ids = []
    for key in tuple(results.keys()):
        if key not in results_ids:
            results.pop(key)
            extra_ids.append(key)
    return extra_ids


def get_signed_impression_blob_from_results(adzerk_results):
    impressions = [
        result.get('impression') for result in adzerk_results.values()
        if result.get('impression')]
    if not impressions:
        return None
    signer = TimestampSigner()
    return signer.sign(','.join(impressions))


def unsign_signed_blob(blob, timeout):
    signer = TimestampSigner()
    try:
        return signer.unsign(blob, timeout)
    except (BadSignature, SignatureExpired) as e:
        raise APIException(e)
