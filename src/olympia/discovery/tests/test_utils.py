# -*- coding: utf-8 -*-
import json

from django.http import HttpResponse

import mock
import pytest
import requests
import settings

from olympia import amo
from olympia.amo.tests import addon_factory
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.utils import (
    call_recommendation_server, get_disco_recommendations, replace_extensions)


@pytest.mark.django_db
@mock.patch('olympia.discovery.utils.statsd.incr')
@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_fails_nice(requests_get, statsd_incr):
    requests_get.side_effect = requests.exceptions.RequestException()
    # Check the exception in requests.get is handled okay.
    assert call_recommendation_server(
        settings.RECOMMENDATION_ENGINE_URL, '123456', {}) is None
    statsd_incr.assert_called_with('services.recommendations.fail')


@pytest.mark.django_db
@mock.patch('olympia.discovery.utils.statsd.incr')
@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_succeeds(requests_get, statsd_incr):
    requests_get.return_value = HttpResponse(
        json.dumps({'results': ['@lolwut']}))
    assert call_recommendation_server(
        settings.RECOMMENDATION_ENGINE_URL, '123456', {}) == ['@lolwut']
    statsd_incr.assert_called_with('services.recommendations.success')


@mock.patch('olympia.discovery.utils.requests.post')
@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_no_parameters(requests_get, requests_post):
    url = settings.RECOMMENDATION_ENGINE_URL
    taar_timeout = settings.RECOMMENDATION_ENGINE_TIMEOUT
    requests_get.return_value = HttpResponse(
        json.dumps({'results': ['@lolwut']}))
    # No parameters
    call_recommendation_server(url, '123456', {})
    requests_get.assert_called_with(url + '123456/', timeout=taar_timeout)
    assert not requests_post.called


@mock.patch('olympia.discovery.utils.requests.post')
@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_some_parameters(
        requests_get, requests_post):
    url = 'http://example.com/whatever/'
    taar_timeout = settings.RECOMMENDATION_ENGINE_TIMEOUT
    requests_get.return_value = HttpResponse(
        json.dumps({'results': ['@lolwut']}))
    data = {'some': 'params', 'and': 'more'}
    call_recommendation_server(url, '123456', data)
    requests_get.assert_called_with(
        url + '123456/?and=more&some=params', timeout=taar_timeout)
    assert not requests_post.called


@mock.patch('olympia.discovery.utils.requests.post')
@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_post(
        requests_get, requests_post):
    url = 'http://example.com/taar_is_awesome/'
    taar_timeout = settings.RECOMMENDATION_ENGINE_TIMEOUT
    requests_get.return_value = HttpResponse(
        json.dumps({'results': ['@lolwut']}))
    data = {'some': 'params', 'and': 'more'}
    call_recommendation_server(url, '4815162342', data, verb='post')
    assert not requests_get.called
    requests_post.assert_called_with(
        url + '4815162342/', json=data, timeout=taar_timeout)


@mock.patch('olympia.discovery.utils.requests.post')
@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_post_no_parameters(
        requests_get, requests_post):
    url = 'http://example.com/taar_is_awesome/'
    taar_timeout = settings.RECOMMENDATION_ENGINE_TIMEOUT
    requests_get.return_value = HttpResponse(
        json.dumps({'results': ['@lolwut']}))
    call_recommendation_server(url, '4815162342', None, verb='post')
    assert not requests_get.called
    requests_post.assert_called_with(
        url + '4815162342/', json=None, timeout=taar_timeout)


@mock.patch('olympia.discovery.utils.call_recommendation_server')
@pytest.mark.django_db
def test_get_disco_recommendations(call_recommendation_server):
    expected_addons = [
        addon_factory(guid='101@mozilla'),
        addon_factory(guid='102@mozilla'),
        addon_factory(guid='103@mozilla'),
        addon_factory(guid='104@mozilla'),
    ]
    # Only the first one has a DiscoveryItem. The rest should still be
    # returned.

    call_recommendation_server.return_value = [
        '101@mozilla', '102@mozilla', '103@mozilla', '104@mozilla'
    ]
    recommendations = get_disco_recommendations('0', [])
    call_recommendation_server.assert_called_with(
        'https://taar.dev.mozaws.net/api/recommendations/', '0', None,
        verb='post')
    assert [result.addon for result in recommendations] == expected_addons

    # only valid, public add-ons should match guids
    incomplete_addon = expected_addons.pop()
    incomplete_addon.update(status=amo.STATUS_NULL)
    # Remove this one and have recommendations return a bad guid instead.
    expected_addons.pop()
    call_recommendation_server.return_value = [
        '101@mozilla', '102@mozilla', '103@badbadguid', '104@mozilla'
    ]
    recommendations = get_disco_recommendations('0', [])
    assert [result.addon for result in recommendations] == expected_addons


@mock.patch('olympia.discovery.utils.call_recommendation_server')
@pytest.mark.django_db
def test_get_disco_recommendations_overrides(call_recommendation_server):
    call_recommendation_server.return_value = [
        '@guid1', '@guid2', '103@mozilla', '104@mozilla'
    ]
    get_disco_recommendations('xxx', ['@guid1', '@guid2', '@guid3'])
    data = {
        'options': {
            'promoted': [
                ['@guid1', 100],
                ['@guid2', 99],
                ['@guid3', 98],
            ]
        }
    }
    call_recommendation_server.assert_called_with(
        'https://taar.dev.mozaws.net/api/recommendations/', 'xxx', data,
        verb='post')


@pytest.mark.django_db
def test_replace_extensions():
    source = [
        DiscoveryItem(addon=addon_factory(), custom_addon_name=u'replacê me'),
        DiscoveryItem(
            addon=addon_factory(), custom_addon_name=u'replace me tøø'),
        DiscoveryItem(
            addon=addon_factory(type=amo.ADDON_PERSONA),
            custom_addon_name=u'ŋot me'),
        DiscoveryItem(
            addon=addon_factory(type=amo.ADDON_PERSONA),
            custom_addon_name=u'ŋor me'),
        DiscoveryItem(addon=addon_factory(), custom_addon_name=u'probably me'),
        DiscoveryItem(
            addon=addon_factory(type=amo.ADDON_PERSONA),
            custom_addon_name=u'safê')
    ]
    # Just 2 replacements
    replacements = [
        DiscoveryItem(
            addon=addon_factory(), custom_addon_name=u'just for you'),
        DiscoveryItem(
            addon=addon_factory(), custom_addon_name=u'and this øne'),
    ]
    result = replace_extensions(source, replacements)
    assert result == [
        replacements[0],
        replacements[1],  # we only had two replacements.
        source[2],
        source[3],
        source[4],
        source[5],
    ], result

    # Add a few more so all extensions are replaced, with one spare.
    replacements.append(DiscoveryItem(
        addon=addon_factory(), custom_addon_name=u'extra ône'))
    replacements.append(DiscoveryItem(
        addon=addon_factory(), custom_addon_name=u'extra tôo'))
    result = replace_extensions(source, replacements)
    assert result == [
        replacements[0],
        replacements[1],
        source[2],  # Not an extension, so not replaced.
        source[3],  # Not an extension, so not replaced.
        replacements[2],
        source[5],  # Not an extension, so not replaced.
    ], result
