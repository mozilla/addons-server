import json
import os
from copy import deepcopy
from unittest import mock

from django.conf import settings

import pytest
from sentry_sdk.hub import Hub

from olympia.core.sentry import get_sentry_release


@mock.patch.dict('os.environ', {'REQUIRE_SENTRY_VERSION': 'True'})
def test_sentry_release_nothing_provided_strict():
    version = {}
    with mock.patch('builtins.open', mock.mock_open(read_data=json.dumps(version))):
        pytest.raises(ValueError, get_sentry_release)


def test_sentry_release_nothing_provided_loose():
    version = {}
    with mock.patch('builtins.open', mock.mock_open(read_data=json.dumps(version))):
        assert get_sentry_release() is None


def test_sentry_release_version_provided():
    version = {'version': '2024.01.01'}
    with mock.patch('builtins.open', mock.mock_open(read_data=json.dumps(version))):
        assert get_sentry_release() == version['version']


def test_sentry_release_commit_provided():
    version = {'commit': 'abc'}
    with mock.patch('builtins.open', mock.mock_open(read_data=json.dumps(version))):
        assert get_sentry_release() == version['commit']


def test_sentry_data_scrubbing():
    sentry_client = Hub.current.client
    before_send = sentry_client.options.get('before_send')
    before_breadcrumb = sentry_client.options.get('before_breadcrumb')
    assert before_send
    assert before_breadcrumb
    assert sentry_client.options.get('send_default_pii') is True
    event_raw = open(
        os.path.join(settings.ROOT, 'src/olympia/amo/fixtures/sentry_event.json')
    ).read()
    event = json.loads(event_raw)
    assert '@bar.com' in event_raw
    assert '172.18.0.1' in event_raw
    assert '127.0.0.42' in event_raw
    assert '127.0.0.43' in event_raw
    assert '4.8.15.16' in event_raw
    assert 'sensitive' in event_raw
    expected_request_data = deepcopy(event['request'])
    expected_frame_data = deepcopy(
        event['exception']['values'][0]['stacktrace']['frames'][3]
    )
    expected_breadcrumb_data = deepcopy(event['breadcrumbs']['values'][5])
    assert len(event['breadcrumbs']['values']) == 9

    # mimic what sentry does: go through every breadcrumb with
    # before_breadcrumb() and the entire event with before_send() (Normally
    # sentry would process breadcrumbs as they are sent, not after the fact,
    # but this should be a good enough approximation).
    event['breadcrumbs']['values'] = list(
        filter(
            None,
            map(
                lambda crumb: before_breadcrumb(crumb, None),
                event['breadcrumbs']['values'],
            ),
        )
    )
    event = before_send(event, None)
    event_raw = json.dumps(event)

    # We keep cookies, user dict.
    assert event['request']['cookies']
    assert event['user']['id']

    # Email is redacted though.
    assert event['user']['email'] == '*** redacted ***'

    # ip_adress is removed completely because sentry checks its format.
    assert 'ip_address' not in event['user']

    # Modify old_request_data according to what we should have done and see if
    # it matches what before_send() did in reality.
    expected_request_data['env']['REMOTE_ADDR'] = '*** redacted ***'
    # Note special case for X-forwarded-for in the 'headers' dict, meant to
    # test we don't care about case.
    expected_request_data['headers']['X-forwarded-for'] = '*** redacted ***'
    assert expected_request_data == event['request']

    # Same for expected_frame_data.
    expected_frame_data['vars']['email'] = '*** redacted ***'
    expected_frame_data['vars']['some_dict']['email'] = '*** redacted ***'
    expected_frame_data['vars']['some_dict']['second_level'][1]['email'] = (
        '*** redacted ***'
    )
    assert (
        expected_frame_data
        == event['exception']['values'][0]['stacktrace']['frames'][3]
    )

    # We removed one sensitive breadcrumb.
    assert len(event['breadcrumbs']['values']) == 8

    # We redacted the rest
    expected_breadcrumb_data['data']['url'] = (
        'https://reputationservice.example.com/...redacted...'
    )
    assert expected_breadcrumb_data == event['breadcrumbs']['values'][5]

    # Sensitive stuff that should have been redacted.
    assert '@bar.com' not in event_raw
    assert '172.18.0.1' not in event_raw
    assert '127.0.0.42' not in event_raw
    assert '127.0.0.43' not in event_raw
    assert '4.8.15.16' not in event_raw
    assert 'sensitive' not in event_raw
