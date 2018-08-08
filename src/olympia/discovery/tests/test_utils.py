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
    call_recommendation_server, get_recommendations, replace_extensions)


@pytest.mark.django_db
@mock.patch('olympia.discovery.utils.statsd.incr')
@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_fails_nice(requests_get, statsd_incr):
    requests_get.side_effect = requests.exceptions.RequestException()
    # Check the exception in requests.get is handled okay.
    assert call_recommendation_server(
        '123456', {}, settings.RECOMMENDATION_ENGINE_URL) is None
    statsd_incr.assert_called_with('services.recommendations.fail')


@pytest.mark.django_db
@mock.patch('olympia.discovery.utils.statsd.incr')
@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_succeeds(requests_get, statsd_incr):
    requests_get.return_value = HttpResponse(
        json.dumps({'results': ['@lolwut']}))
    assert call_recommendation_server(
        '123456', {}, settings.RECOMMENDATION_ENGINE_URL) == ['@lolwut']
    statsd_incr.assert_called_with('services.recommendations.success')


@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_parameters(requests_get):
    taar_url = settings.RECOMMENDATION_ENGINE_URL
    taar_timeout = settings.RECOMMENDATION_ENGINE_TIMEOUT
    requests_get.return_value = HttpResponse(
        json.dumps({'results': ['@lolwut']}))
    # No locale or platform
    call_recommendation_server('123456', {}, taar_url)
    requests_get.assert_called_with(taar_url + '123456/', timeout=taar_timeout)
    # locale no platform
    call_recommendation_server('123456', {'locale': 'en-US'}, taar_url)
    requests_get.assert_called_with(
        taar_url + '123456/?locale=en-US', timeout=taar_timeout)
    # platform no locale
    call_recommendation_server('123456', {'platform': 'WINNT'}, taar_url)
    requests_get.assert_called_with(
        taar_url + '123456/?platform=WINNT', timeout=taar_timeout)
    # both locale and platform
    call_recommendation_server(
        '123456', {'locale': 'en-US', 'platform': 'WINNT'}, taar_url)
    requests_get.assert_called_with(
        taar_url + '123456/?locale=en-US&platform=WINNT', timeout=taar_timeout)
    # and some extra parameters
    call_recommendation_server(
        '123456',
        {'locale': 'en-US', 'platform': 'WINNT', 'study': 'sch',
         'branch': 'tree'},
        settings.RECOMMENDATION_ENGINE_URL)
    requests_get.assert_called_with(
        taar_url + '123456/?branch=tree&locale=en-US&platform=WINNT&study=sch',
        timeout=taar_timeout)


@mock.patch('olympia.discovery.utils.call_recommendation_server')
@pytest.mark.django_db
def test_get_recommendations(call_recommendation_server):
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
    recommendations = get_recommendations(
        '0', {'locale': 'en-US', 'platform': 'WINNT'})
    assert [r.addon for r in recommendations] == expected_addons

    # only valid, public add-ons should match guids
    incomplete_addon = expected_addons.pop()
    incomplete_addon.update(status=amo.STATUS_NULL)
    # Remove this one and have recommendations return a bad guid instead.
    expected_addons.pop()
    call_recommendation_server.return_value = [
        '101@mozilla', '102@mozilla', '103@badbadguid', '104@mozilla'
    ]
    recommendations = get_recommendations(
        '0', {'locale': 'en-US', 'platform': 'WINNT'})
    assert [result.addon for result in recommendations] == expected_addons


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
