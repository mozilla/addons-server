# -*- coding: utf-8 -*-
import json
import mock
import pytest
import requests
from django.http import HttpResponse

from olympia import amo
from olympia.amo.tests import addon_factory
from olympia.discovery.data import DiscoItem
from olympia.discovery.utils import (
    call_recommendation_server, get_recommendations, replace_extensions)


@pytest.mark.django_db
@mock.patch('olympia.discovery.utils.statsd.incr')
@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_fails_nice(requests_get, statsd_incr):
    requests_get.side_effect = requests.exceptions.RequestException()
    # Check the exception in requests.get is handled okay.
    assert call_recommendation_server('123456') == []
    assert statsd_incr.called_with('services.recommendations.fail')


@pytest.mark.django_db
@mock.patch('olympia.discovery.utils.statsd.incr')
@mock.patch('olympia.discovery.utils.requests.get')
def test_call_recommendation_server_succeeds(requests_get, statsd_incr):
    requests_get.return_value = HttpResponse(
        json.dumps({'results': ['@lolwut']}))
    assert call_recommendation_server('123456') == ['@lolwut']
    assert statsd_incr.called_with('services.recommendations.succeed')


@mock.patch('olympia.discovery.utils.call_recommendation_server')
@pytest.mark.django_db
def test_get_recommendations(call_recommendation_server):
    a101 = addon_factory(id=101, guid='101@mozilla')
    addon_factory(id=102, guid='102@mozilla')
    addon_factory(id=103, guid='103@mozilla')
    addon_factory(id=104, guid='104@mozilla')

    call_recommendation_server.return_value = [
        '101@mozilla', '102@mozilla', '103@mozilla', '104@mozilla'
    ]
    assert ([r.addon_id for r in get_recommendations('0')] ==
            [101, 102, 103, 104])
    assert all([r.is_recommendation for r in get_recommendations('0')])

    # only valid, public add-ons should match guids
    a101.update(status=amo.STATUS_NULL)
    call_recommendation_server.return_value = [
        '101@mozilla', '102@mozilla', '103@mozilla', '104@badguid'
    ]
    assert ([r.addon_id for r in get_recommendations('0')] ==
            [102, 103])


def test_replace_extensions():
    source = [
        DiscoItem(addon_id=101, addon_name=u'replacê me'),
        DiscoItem(addon_id=102, addon_name=u'replace me tøø'),
        DiscoItem(addon_id=103, addon_name=u'ŋot me', type=amo.ADDON_PERSONA),
        DiscoItem(addon_id=104, addon_name=u'ŋor me', type=amo.ADDON_PERSONA),
        DiscoItem(addon_id=105, addon_name=u'probably me'),
        DiscoItem(addon_id=106, addon_name=u'safê', type=amo.ADDON_PERSONA),
    ]
    # Just 2 replacements
    replacements = [
        DiscoItem(addon_id=999, addon_name=u'just for you'),
        DiscoItem(addon_id=998, addon_name=u'and this øne'),
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
    replacements.append(DiscoItem(addon_id=997, addon_name='extra one'))
    replacements.append(DiscoItem(addon_id=997, addon_name='extra too'))
    result = replace_extensions(source, replacements)
    assert result == [
        replacements[0],
        replacements[1],
        source[2],  # Not an extension, so not replaced.
        source[3],  # Not an extension, so not replaced.
        replacements[2],
        source[5],  # Not an extension, so not replaced.
    ], result
