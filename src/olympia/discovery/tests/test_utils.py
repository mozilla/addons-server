import json

from django.conf import settings
from django.http import HttpResponse

import pytest
import requests
from unittest import mock
from waffle.testutils import override_switch

from olympia import amo
from olympia.amo.tests import addon_factory, TestCase
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.utils import (
    call_recommendation_server,
    get_disco_recommendations,
    replace_extensions,
)


valid_client_id = '67c831b793cc423eb482de7421459d2b1faf4cc0fef04c30b03ebb62e91fa1bf'


class TestCallRecommendationServer(TestCase):
    @override_switch('enable-taar', active=False)
    @mock.patch('olympia.discovery.utils.statsd.incr')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_waffle_switch_off(self, requests_get, statsd_incr):
        requests_get.side_effect = AssertionError  # Shouldn't be reached.
        assert (
            call_recommendation_server(
                settings.RECOMMENDATION_ENGINE_URL, valid_client_id, {}
            )
            is None
        )
        assert statsd_incr.call_count == 0

    @mock.patch('olympia.discovery.utils.statsd.incr')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_catches_errors(self, requests_get, statsd_incr):
        requests_get.side_effect = requests.exceptions.RequestException()
        # Check the exception in requests.get is handled okay.
        assert (
            call_recommendation_server(
                settings.RECOMMENDATION_ENGINE_URL, valid_client_id, {}
            )
            is None
        )
        statsd_incr.assert_called_with('services.recommendations.fail')

    @mock.patch('olympia.discovery.utils.statsd.incr')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_catches_responses_errors(
        self, requests_get, statsd_incr
    ):
        requests_get.return_value.raise_for_status.side_effect = (
            requests.exceptions.HTTPError
        )
        # Check the exception in repsonse.raise_for_status() is handled okay.
        assert (
            call_recommendation_server(
                settings.RECOMMENDATION_ENGINE_URL, valid_client_id, {}
            )
            is None
        )
        statsd_incr.assert_called_with('services.recommendations.fail')

    @mock.patch('olympia.discovery.utils.statsd.incr')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_timeouts_are_ignored(
        self, requests_get, statsd_incr
    ):
        requests_get.side_effect = requests.exceptions.ConnectTimeout
        # Check the exception in requests.get is handled okay.
        assert (
            call_recommendation_server(
                settings.RECOMMENDATION_ENGINE_URL, valid_client_id, {}
            )
            is None
        )
        statsd_incr.assert_called_with('services.recommendations.fail')

    @mock.patch('olympia.discovery.utils.statsd.incr')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_succeeds(self, requests_get, statsd_incr):
        requests_get.return_value = mock.Mock(
            spec=requests.Response,
            content=json.dumps({'results': ['@lolwut']}),
        )
        assert call_recommendation_server(
            settings.RECOMMENDATION_ENGINE_URL, valid_client_id, {}
        ) == ['@lolwut']
        statsd_incr.assert_called_with('services.recommendations.success')

    @mock.patch('olympia.discovery.utils.requests.post')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_no_parameters(
        self, requests_get, requests_post
    ):
        url = settings.RECOMMENDATION_ENGINE_URL
        requests_get.return_value = mock.Mock(
            spec=requests.Response,
            content=json.dumps({'results': ['@lolwut']}),
        )
        # No parameters
        assert call_recommendation_server(url, valid_client_id, {})
        requests_get.assert_called_with(
            url + valid_client_id + '/', timeout=settings.RECOMMENDATION_ENGINE_TIMEOUT
        )
        assert not requests_post.called

    @mock.patch('olympia.discovery.utils.requests.post')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_some_parameters(
        self, requests_get, requests_post
    ):
        url = 'http://example.com/whatever/'
        requests_get.return_value = mock.Mock(
            spec=requests.Response,
            content=json.dumps({'results': ['@lolwut']}),
        )
        data = {'some': 'params', 'and': 'moré'}
        assert call_recommendation_server(url, valid_client_id, data)
        requests_get.assert_called_with(
            url + valid_client_id + '/?and=mor%C3%A9&some=params',
            timeout=settings.RECOMMENDATION_ENGINE_TIMEOUT,
        )
        assert not requests_post.called

    @mock.patch('olympia.discovery.utils.requests.post')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_post(self, requests_get, requests_post):
        requests_post.return_value = mock.Mock(
            spec=requests.Response,
            content=json.dumps({'results': ['@lolwut']}),
        )
        url = 'http://example.com/taar_is_awesome/'
        data = {'some': 'params', 'and': 'more'}
        assert call_recommendation_server(url, valid_client_id, data, verb='post')
        assert not requests_get.called
        requests_post.assert_called_with(
            url + valid_client_id + '/',
            json=data,
            timeout=settings.RECOMMENDATION_ENGINE_TIMEOUT,
        )

    @mock.patch('olympia.discovery.utils.requests.post')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_post_no_parameters(
        self, requests_get, requests_post
    ):
        requests_post.return_value = mock.Mock(
            spec=requests.Response,
            content=json.dumps({'results': ['@lolwut']}),
        )
        url = 'http://example.com/taar_is_awesome/'
        assert call_recommendation_server(url, valid_client_id, None, verb='post')
        assert not requests_get.called
        requests_post.assert_called_with(
            url + valid_client_id + '/',
            json=None,
            timeout=settings.RECOMMENDATION_ENGINE_TIMEOUT,
        )

    @mock.patch('olympia.discovery.utils.requests.post')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_get_parameter_is_invalid(
        self, requests_get, requests_post
    ):
        url = 'http://example.com/taar_is_awesome/'
        requests_get.return_value = HttpResponse(json.dumps({'results': []}))

        assert (
            call_recommendation_server(url, "a@b.com' and 1=1", {}, verb='get') is None
        )
        assert not requests_get.called
        assert not requests_post.called

    @mock.patch('olympia.discovery.utils.requests.post')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_get_parameter_is_an_url(
        self, requests_get, requests_post
    ):
        url = 'http://example.com/taar_is_awesome/'
        requests_get.return_value = HttpResponse(json.dumps({'results': []}))

        assert (
            call_recommendation_server(url, 'http://evil.com', {}, verb='get') is None
        )
        assert not requests_get.called
        assert not requests_post.called

        assert (
            call_recommendation_server(url, 'http://evil.com/', {}, verb='get') is None
        )
        assert not requests_get.called
        assert not requests_post.called

        assert (
            call_recommendation_server(url, 'http://[evil.com/', {}, verb='get') is None
        )
        assert not requests_get.called
        assert not requests_post.called

        assert (
            call_recommendation_server(url, 'http://evil.com/foo', {}, verb='get')
            is None
        )
        assert not requests_get.called
        assert not requests_post.called

        assert call_recommendation_server(url, '/foo', {}, verb='get') is None
        assert not requests_get.called
        assert not requests_post.called

        assert call_recommendation_server(url, '//foo', {}, verb='get') is None
        assert not requests_get.called
        assert not requests_post.called

    @mock.patch('olympia.discovery.utils.requests.post')
    @mock.patch('olympia.discovery.utils.requests.get')
    def test_call_recommendation_server_post_parameter_is_an_url(
        self, requests_get, requests_post
    ):
        url = 'http://example.com/taar_is_awesome/'
        requests_post.return_value = HttpResponse(json.dumps({'results': []}))

        assert (
            call_recommendation_server(url, 'http://evil.com', {}, verb='post') is None
        )
        assert not requests_get.called
        assert not requests_post.called

        assert (
            call_recommendation_server(url, 'http://evil.com/', {}, verb='post') is None
        )
        assert not requests_get.called
        assert not requests_post.called

        assert (
            call_recommendation_server(url, 'http://[evil.com/', {}, verb='post')
            is None
        )
        assert not requests_get.called
        assert not requests_post.called

        assert (
            call_recommendation_server(url, 'http://evil.com/foo', {}, verb='post')
            is None
        )
        assert not requests_get.called
        assert not requests_post.called

        assert call_recommendation_server(url, '/foo', {}, verb='post') is None
        assert not requests_get.called
        assert not requests_post.called

        assert call_recommendation_server(url, '//foo', {}, verb='post') is None
        assert not requests_get.called
        assert not requests_post.called


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
        '101@mozilla',
        '102@mozilla',
        '103@mozilla',
        '104@mozilla',
    ]
    recommendations = get_disco_recommendations('0', [])
    call_recommendation_server.assert_called_with(
        'https://taar.dev.mozaws.net/v1/api/recommendations/', '0', None, verb='post'
    )
    assert [result.addon for result in recommendations] == expected_addons

    # only valid, public add-ons should match guids
    incomplete_addon = expected_addons.pop()
    incomplete_addon.update(status=amo.STATUS_NULL)
    # Remove this one and have recommendations return a bad guid instead.
    expected_addons.pop()
    call_recommendation_server.return_value = [
        '101@mozilla',
        '102@mozilla',
        '103@badbadguid',
        '104@mozilla',
    ]
    recommendations = get_disco_recommendations('0', [])
    assert [result.addon for result in recommendations] == expected_addons


@mock.patch('olympia.discovery.utils.call_recommendation_server')
def test_get_disco_recommendations_empty(call_recommendation_server):
    call_recommendation_server.return_value = None
    recommendations = get_disco_recommendations('0', [])
    assert recommendations == []
    call_recommendation_server.assert_called_with(
        'https://taar.dev.mozaws.net/v1/api/recommendations/', '0', None, verb='post'
    )


@mock.patch('olympia.discovery.utils.call_recommendation_server')
@pytest.mark.django_db
def test_get_disco_recommendations_overrides(call_recommendation_server):
    call_recommendation_server.return_value = [
        '@guid1',
        '@guid2',
        '103@mozilla',
        '104@mozilla',
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
        'https://taar.dev.mozaws.net/v1/api/recommendations/', 'xxx', data, verb='post'
    )


@pytest.mark.django_db
def test_replace_extensions():
    source = [
        DiscoveryItem(addon=addon_factory()),  # replaced
        DiscoveryItem(addon=addon_factory()),  # also replaced
        DiscoveryItem(addon=addon_factory(type=amo.ADDON_STATICTHEME)),  # not
        DiscoveryItem(addon=addon_factory(type=amo.ADDON_STATICTHEME)),  # nope
        DiscoveryItem(addon=addon_factory()),  # possibly replaced
        DiscoveryItem(addon=addon_factory(type=amo.ADDON_STATICTHEME)),  # nope
    ]
    # Just 2 replacements
    replacements = [
        DiscoveryItem(addon=addon_factory()),
        DiscoveryItem(addon=addon_factory()),
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
    replacements.append(DiscoveryItem(addon=addon_factory()))
    replacements.append(DiscoveryItem(addon=addon_factory()))
    result = replace_extensions(source, replacements)
    assert result == [
        replacements[0],
        replacements[1],
        source[2],  # Not an extension, so not replaced.
        source[3],  # Not an extension, so not replaced.
        replacements[2],
        source[5],  # Not an extension, so not replaced.
    ], result
