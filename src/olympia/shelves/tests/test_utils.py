import json
import os
from collections import namedtuple
from datetime import timedelta
from unittest import mock, TestCase

from django.conf import settings
from django.core.signing import TimestampSigner
from django.utils.encoding import force_bytes

from rest_framework.exceptions import APIException

import responses
from freezegun import freeze_time

from ..utils import (
    call_adzerk_server,
    filter_adzerk_results_to_es_results_qs,
    get_addons_from_adzerk,
    get_signed_impression_blob_from_results,
    unsign_signed_blob,
    process_adzerk_results,
    send_event_ping,
    send_impression_pings)


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
            'impression': r'i.gif%3Fe%3DeyJ2IjLtgBug',
            'click': r'r%3Fe%3DeyJ2IjoiMS42IiwiYXLCA%26noredirect',
            'conversion': r'e.gif%3Fjefoijef3ddfijdf',
        },
        '566314': {
            'impression': r'i.gif%3Fe%3DeyJ2IjoNtSz8',
            'click': r'r%3Fe%3DeyJ2IjoiMS42IiwiYU5Hw%26noredirect',
            'conversion': r'e.gif%3Fe%3De3jfiojef%26f%3Ddfef',
        },
    }


@mock.patch('olympia.shelves.utils.statsd.incr')
def test_call_adzerk_server(statsd_mock):
    responses.add(
        responses.POST,
        settings.ADZERK_URL,
        json=adzerk_json)
    site_id = settings.ADZERK_SITE_ID
    network_id = settings.ADZERK_NETWORK_ID
    data = {
        'placements': [
            {
                "divName": 'multi',
                "networkId": network_id,
                "siteId": site_id,
                "adTypes": [5],
                "count": 3,
            },
        ]}
    results = call_adzerk_server(settings.ADZERK_URL, data)
    assert responses.calls[0].request.body == force_bytes(json.dumps(
        data))
    # we're using a real response that only contains two divs
    assert len(results['decisions']['multi']) == 2
    statsd_mock.assert_called_with('services.adzerk.success')


@mock.patch('olympia.shelves.utils.statsd.incr')
def test_call_adzerk_server_empty_response(statsd_mock):
    responses.add(
        responses.POST,
        settings.ADZERK_URL)
    results = call_adzerk_server(settings.ADZERK_URL)
    assert results == {}
    statsd_mock.assert_called_with('services.adzerk.fail')

    statsd_mock.reset_mock()
    responses.add(
        responses.POST,
        settings.ADZERK_URL,
        status=500,
        json={})
    results = call_adzerk_server(settings.ADZERK_URL)
    assert results == {}
    statsd_mock.assert_called_with('services.adzerk.fail')


def test_process_adzerk_results():
    assert process_adzerk_results(response={}) == {}

    response = {
        'decisions': {'multi': [
            {
                "clickUrl": "https://e-9999.adzerk.net/r?e=eyJ2IjoiMS42I&iwiA",
                "impressionUrl": "https://e-9999.adzerk.net/i.gif?e=eyJ2I&jLg",
                "contents": [{
                    "data": {
                        "customData": {
                            "id": "1234"
                        }
                    },
                }],
                "events": [{
                    "id": 2,
                    "url": "https://e-9999.adzerk.net/e.gif?e=454545"
                }]
            },
            {
                "clickUrl": "https://e-9999.adzerk.net/r?e=different",
                "impressionUrl": "https://e-9999.adzerk.net/i.gif?e=values",
                "contents": [{
                    "data": {
                        "customData": {
                            "id": "1234"  # duplicate id with foo1
                        }
                    },
                }],
                "events": [{
                    "id": 2,
                    "url": "https://e-9999.adzerk.net/e.gif?e=787878"
                }]
            },
            {
                "clickUrl": "https://e-9999.adzerk.net/r?e=eyJ2IjoiMS42IiwiA",
                "impressionUrl": "https://e-9999.adzerk.net/i.gif?e=eyJ2IjLg",
                "contents": [{
                    "data": {
                        "customData": {
                            "id": "not-a-number"
                        }
                    },
                }],
                "events": []
            },
            {
                "clickUrl": "https://e-9999.adzerk.net/r?e=ey44545",
                "impressionUrl": "https://e-9999.adzerk.net/i.gif?e=thesfsg",
                "contents": [{
                    "data": {
                        "customData": {
                            "id": "1"
                        }
                    },
                }],
                "events": [{
                    "id": 2,
                    "url": ""
                }]
            },
        ]}
    }
    results = process_adzerk_results(response)
    assert results == {
        '1234': {
            'impression': r'i.gif%3Fe%3DeyJ2I%26jLg',
            'click': r'r%3Fe%3DeyJ2IjoiMS42I%26iwiA%26noredirect',
            'conversion': r'e.gif%3Fe%3D454545'
        },
        '1': {
            'impression': r'i.gif%3Fe%3Dthesfsg',
            'click': r'r%3Fe%3Dey44545%26noredirect',
            'conversion': '',
        }
    }


@mock.patch('olympia.shelves.utils.process_adzerk_results')
@mock.patch('olympia.shelves.utils.call_adzerk_server')
def test_get_addons_from_adzerk(call_server_mock, process_mock):
    site_id = settings.ADZERK_SITE_ID
    network_id = settings.ADZERK_NETWORK_ID
    data = {
        'placements': [
            {
                "divName": 'multi',
                "networkId": network_id,
                "siteId": site_id,
                "adTypes": [5],
                "eventIds": [2],
                "count": 2,
            },
        ]}

    call_server_mock.return_value = None
    process_mock.return_value = {'thing': {}}
    assert get_addons_from_adzerk(2) == {}
    call_server_mock.assert_called_with(
        settings.ADZERK_URL, data)
    process_mock.assert_not_called()

    call_server_mock.return_value = {'something': 'something'}
    assert get_addons_from_adzerk(3) == {'thing': {}}
    data['placements'][0]['count'] = 3
    call_server_mock.assert_called_with(
        settings.ADZERK_URL, data)
    process_mock.assert_called_with(
        {'something': 'something'})


@mock.patch('olympia.shelves.utils.statsd.incr')
def test_send_impression_pings(incr_mock):
    impressions = [
        r'i.gif%3Fe%3DeyJ2IjLtg%26Bug',
        r'i.gif%3Fe%3DeyJ2IjoNtSz8',
    ]
    responses.add(
        responses.GET,
        settings.ADZERK_EVENT_URL + 'i.gif?e=eyJ2IjLtg&Bug')
    responses.add(
        responses.GET,
        settings.ADZERK_EVENT_URL + 'i.gif?e=eyJ2IjoNtSz8')

    signer = TimestampSigner()
    send_impression_pings(signer.sign(','.join(impressions)))
    incr_mock.assert_called_with('services.adzerk.impression.success')
    assert responses.calls[0].request.url == (
        settings.ADZERK_EVENT_URL + 'i.gif?e=eyJ2IjLtg&Bug')
    assert responses.calls[1].request.url == (
        settings.ADZERK_EVENT_URL + 'i.gif?e=eyJ2IjoNtSz8')


@mock.patch('olympia.shelves.utils.statsd.incr')
def test_send_event_ping(incr_mock):
    click = r'r%3Fe%3DeyJ2IjLtg%26Bug'
    responses.add(
        responses.GET,
        settings.ADZERK_EVENT_URL + 'r?e=eyJ2IjLtg&Bug')

    signer = TimestampSigner()
    send_event_ping(signer.sign(click), 'foo')
    incr_mock.assert_called_with('services.adzerk.foo.success')
    assert responses.calls[0].request.url == (
        settings.ADZERK_EVENT_URL + 'r?e=eyJ2IjLtg&Bug')


def test_filter_adzerk_results_to_es_results_qs():
    results = {
        '99': {},
        '123': {},
        '33': {},
    }
    hit = namedtuple('hit', 'id')
    es_results = [
        hit(99),
        hit(66),
        hit(33),
    ]
    extras = filter_adzerk_results_to_es_results_qs(results, es_results)
    assert results == {
        '99': {},
        '33': {}
    }
    assert extras == ['123']


@freeze_time('2020-01-01')
def test_get_signed_impression_blob_from_results():
    signer = TimestampSigner()
    results = {
        '66': {
            'addon_id': 66,
            'impression': '123456',
            'click': 'abcdef'},
        '99': {
            'addon_id': 99,
            'impression': '012345',
            'click': 'bcdefg'},
    }
    blob = get_signed_impression_blob_from_results(results)
    assert blob == signer.sign('123456,012345')
    assert blob == '123456,012345:1imRQe:bYOCLk1ZS18trP34EnE8Ph5ykFI'


def test_unsign_signed_blob():
    blob = '123456,012345:1imRQe:bYOCLk1ZS18trP34EnE8Ph5ykFI'
    with freeze_time('2020-01-01') as freezer:
        # bad
        with TestCase.assertRaises(None, APIException):
            unsign_signed_blob('.' + blob, 1)

        # good
        impressions = unsign_signed_blob(blob, 1).split(',')
        assert impressions == ['123456', '012345']

        # good, but now stale
        freezer.tick(delta=timedelta(seconds=61))
        with TestCase.assertRaises(None, APIException):
            unsign_signed_blob(blob, 60)
