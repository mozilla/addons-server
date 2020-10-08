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
    get_impression_data_from_signed_blob,
    process_adzerk_results,
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
            'impression': 'e%3DeyJ2IjLtgBug',
            'click': 'e%3DeyJ2IjoiMS42IiwiYXLCA',
            'addon_id': '415198'},
        '566314': {
            'impression': 'e%3DeyJ2IjoNtSz8',
            'click': 'e%3DeyJ2IjoiMS42IiwiYU5Hw',
            'addon_id': '566314'},
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
        ]}
    results = call_adzerk_server(settings.ADZERK_URL, data)
    assert responses.calls[0].request.body == force_bytes(json.dumps(
        data))
    assert 'div0' in results['decisions']
    assert 'div1' in results['decisions']
    # we're using a real response that only contains two divs
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
    placeholders = ['foo1', 'foo2', 'foo3', 'foo4', 'foo5']
    assert process_adzerk_results(response={}, placeholders=placeholders) == {}

    response = {
        'decisions': {
            'foo1': {
                "clickUrl": "https://e-9999.adzerk.net/r?e=eyJ2IjoiMS42I&iwiA",
                "impressionUrl": "https://e-9999.adzerk.net/i.gif?e=eyJ2I&jLg",
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
        }
    }
    results = process_adzerk_results(response, placeholders)
    assert results == {
        '1234': {
            'impression': 'e%3DeyJ2I%26jLg',
            'click': 'e%3DeyJ2IjoiMS42I%26iwiA',
            'addon_id': '1234',
        },
        '1': {
            'impression': 'e%3Dthesfsg',
            'click': 'e%3Dey44545',
            'addon_id': '1',
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
                "divName": 'div0',
                "networkId": network_id,
                "siteId": site_id,
                "adTypes": [5]},
            {
                "divName": 'div1',
                "networkId": network_id,
                "siteId": site_id,
                "adTypes": [5]},
        ]}

    call_server_mock.return_value = None
    process_mock.return_value = {'thing': {}}
    assert get_addons_from_adzerk(2) == {}
    call_server_mock.assert_called_with(
        settings.ADZERK_URL, data)
    process_mock.assert_not_called()

    call_server_mock.return_value = {'something': 'something'}
    assert get_addons_from_adzerk(3) == {'thing': {}}
    data['placements'].append(
        {
            "divName": 'div2',
            "networkId": network_id,
            "siteId": site_id,
            "adTypes": [5]},
    )
    call_server_mock.assert_called_with(
        settings.ADZERK_URL, data)
    process_mock.assert_called_with(
        {'something': 'something'}, ['div0', 'div1', 'div2'])


@mock.patch('olympia.shelves.utils.statsd.incr')
def test_send_impression_pings(incr_mock):
    impressions = [
        'e%3DeyJ2IjLtg%26Bug',
        'e%3DeyJ2IjoNtSz8',
    ]
    responses.add(
        responses.GET,
        settings.ADZERK_IMPRESSION_URL + 'e=eyJ2IjLtg&Bug')
    responses.add(
        responses.GET,
        settings.ADZERK_IMPRESSION_URL + 'e=eyJ2IjoNtSz8')

    send_impression_pings(impressions)
    incr_mock.assert_called_with('services.adzerk.impression.success')


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
    filter_adzerk_results_to_es_results_qs(results, es_results)
    assert results == {
        '99': {},
        '33': {}
    }


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


def test_get_impression_data_from_signed_blob():
    blob = '123456,012345:1imRQe:bYOCLk1ZS18trP34EnE8Ph5ykFI'
    with freeze_time('2020-01-01') as freezer:
        # bad
        with TestCase.assertRaises(None, APIException):
            get_impression_data_from_signed_blob('.' + blob)

        # good
        impressions = get_impression_data_from_signed_blob(blob)
        assert impressions == ['123456', '012345']

        # good, but now stale
        freezer.tick(delta=timedelta(seconds=61))
        with TestCase.assertRaises(None, APIException):
            get_impression_data_from_signed_blob(blob)
