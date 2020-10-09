import json
import os
from unittest import mock

from django.conf import settings
from django.utils.encoding import force_bytes

import responses

from ..utils import (
    call_adzerk_server, get_addons_from_adzerk, process_adzerk_results)


# This is a copy of a response from adzerk (with click and impressions trimmed)
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
adzerk_response = os.path.join(TESTS_DIR, 'adzerk', 'adzerk_2.json')
with open(adzerk_response) as file_object:
    adzerk_json = json.load(file_object)


def test_get_addons_from_adzerk_full():
    responses.add(
        responses.POST,
        settings.ADZERK_URL,
        json=adzerk_json)
    results = get_addons_from_adzerk(4)
    assert results == {
        '415198': {
            'impression': 'e=eyJ2IjLtgBug',
            'click': 'e=eyJ2IjoiMS42IiwiYXLCA',
            'addon_id': '415198'},
        '566314': {
            'impression': 'e=eyJ2IjoNtSz8',
            'click': 'e=eyJ2IjoiMS42IiwiYU5Hw',
            'addon_id': '566314'},
    }


@mock.patch('olympia.shelves.utils.statsd.incr')
def test_call_adzerk_server(statsd_mock):
    responses.add(
        responses.POST,
        settings.ADZERK_URL,
        json=adzerk_json)
    placeholders = ['div0', 'div1', 'div2']
    site_id = settings.ADZERK_SITE_ID
    network_id = settings.ADZERK_NETWORK_ID
    results = call_adzerk_server(placeholders)
    assert responses.calls[0].request.body == force_bytes(json.dumps(
        {'placements': [
            {
                "divName": 'div0',
                "networkId": network_id,
                "siteId": site_id,
                "adTypes": [5]},
            {
                "divName": 'div1',
                "networkId": network_id,
                "siteId": site_id,
                "adTypes": [5]},
            {
                "divName": 'div2',
                "networkId": network_id,
                "siteId": site_id,
                "adTypes": [5]},
        ]}))
    assert 'div0' in results['decisions']
    assert 'div1' in results['decisions']
    # we're using a real response that only contains two divs
    statsd_mock.assert_called_with('services.adzerk.success')


@mock.patch('olympia.shelves.utils.statsd.incr')
def test_call_adzerk_server_empty_response(statsd_mock):
    placeholders = ['div1', 'div2', 'div3']

    responses.add(
        responses.POST,
        settings.ADZERK_URL)
    results = call_adzerk_server(placeholders)
    assert results == {}
    statsd_mock.assert_called_with('services.adzerk.fail')

    statsd_mock.reset_mock()
    responses.add(
        responses.POST,
        settings.ADZERK_URL,
        status=500,
        json={})
    results = call_adzerk_server(placeholders)
    assert results == {}
    statsd_mock.assert_called_with('services.adzerk.fail')


def test_process_adzerk_results():
    placeholders = ['foo1', 'foo2', 'foo3', 'foo4', 'foo5']
    assert process_adzerk_results(response={}, placeholders=placeholders) == {}

    response = {
        'decisions': {
            'foo1': {
                "clickUrl": "https://e-9999.adzerk.net/r?e=eyJ2IjoiMS42IiwiA",
                "impressionUrl": "https://e-9999.adzerk.net/i.gif?e=eyJ2IjLg",
                "contents": [{
                    "data": {
                        "customData": {
                            "id": "1234"
                        }
                    },
                }],
            },
            'foo2': {
                "clickUrl": "https://e-9999.adzerk.net/r?e=different",
                "impressionUrl": "https://e-9999.adzerk.net/i.gif?e=values",
                "contents": [{
                    "data": {
                        "customData": {
                            "id": "1234"  # duplicate id with foo1
                        }
                    },
                }],
            },
            'foo3': {
                "clickUrl": "https://e-9999.adzerk.net/r?e=eyJ2IjoiMS42IiwiA",
                "impressionUrl": "https://e-9999.adzerk.net/i.gif?e=eyJ2IjLg",
                "contents": [{
                    "data": {
                        "customData": {
                            "id": "not-a-number"
                        }
                    },
                }],
            },
            # no foo4
            'extrafoo': {
                "clickUrl": "https://e-9999.adzerk.net/r?e=eyJ2IjoiMS42IiwiA",
                "impressionUrl": "https://e-9999.adzerk.net/i.gif?e=eyJ2IjLg",
                "contents": [{
                    "data": {
                        "customData": {
                            "id": "5565"
                        }
                    },
                }],
            },
            'foo5': {
                "clickUrl": "https://e-9999.adzerk.net/r?e=ey44545",
                "impressionUrl": "https://e-9999.adzerk.net/i.gif?e=thesfsg",
                "contents": [{
                    "data": {
                        "customData": {
                            "id": "1"
                        }
                    },
                }],
            },
            'foo6': None,
        }
    }
    results = process_adzerk_results(response, placeholders)
    assert results == {
        '1234': {
            'impression': 'e=eyJ2IjLg',
            'click': 'e=eyJ2IjoiMS42IiwiA',
            'addon_id': '1234',
        },
        '1': {
            'impression': 'e=thesfsg',
            'click': 'e=ey44545',
            'addon_id': '1',
        }
    }


@mock.patch('olympia.shelves.utils.process_adzerk_results')
@mock.patch('olympia.shelves.utils.call_adzerk_server')
def test_get_addons_from_adzerk(call_server_mock, process_mock):
    call_server_mock.return_value = None
    process_mock.return_value = {'thing': {}}
    assert get_addons_from_adzerk(2) == {}
    call_server_mock.assert_called_with(['div0', 'div1'])
    process_mock.assert_not_called()

    call_server_mock.return_value = {'something': 'something'}
    assert get_addons_from_adzerk(3) == {'thing': {}}
    call_server_mock.assert_called_with(['div0', 'div1', 'div2'])
    process_mock.assert_called_with(
        {'something': 'something'}, ['div0', 'div1', 'div2'])
