import os
import json

from copy import deepcopy

import pytest
from sentry_sdk.hub import Hub

from django.conf import settings

from olympia.core.sentry import get_sentry_release


def test_sentry_release_config():
    version_json = os.path.join(settings.ROOT, 'version.json')
    original = None
    sentry_client = Hub.current.client
    current_release = sentry_client.options.get('release')
    assert get_sentry_release() == current_release

    # There is a version.json that contains `version: origin/master`
    # by default in the repository. We should ignore that and fetch
    # the git commit.
    assert len(get_sentry_release()) == 40

    # Cleanup for tests
    if os.path.exists(version_json):
        with open(version_json) as fobj:
            original = fobj.read()

        os.remove(version_json)

    # by default, if no version.json exists it simply fetches a git-sha
    assert len(get_sentry_release()) == 40

    # It fetches `version` from the version.json
    with open(version_json, 'w') as fobj:
        fobj.write(json.dumps({'version': '2018.07.19'}))

    assert get_sentry_release() == '2018.07.19'

    os.remove(version_json)

    # Or tries to get the commit from version.json alternatively
    with open(version_json, 'w') as fobj:
        fobj.write(json.dumps({'commit': '1111111'}))

    assert get_sentry_release() == '1111111'

    if original:
        with open(version_json, 'w') as fobj:
            fobj.write(original)

    # Usual state of things, version is empty but commit is set
    with open(version_json, 'w') as fobj:
        fobj.write(json.dumps({'version': '', 'commit': '1111111'}))

    assert get_sentry_release() == '1111111'

    if original:
        with open(version_json, 'w') as fobj:
            fobj.write(original)


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
    expected_frame_data['vars']['some_dict']['second_level'][1][
        'email'
    ] = '*** redacted ***'
    assert (
        expected_frame_data
        == event['exception']['values'][0]['stacktrace']['frames'][3]
    )

    # We removed one sensitive breadcrumb.
    assert len(event['breadcrumbs']['values']) == 8

    # We redacted the rest
    expected_breadcrumb_data['data'][
        'url'
    ] = 'https://reputationservice.example.com/...redacted...'
    assert expected_breadcrumb_data == event['breadcrumbs']['values'][5]

    # Sensitive stuff that should have been redacted.
    assert '@bar.com' not in event_raw
    assert '172.18.0.1' not in event_raw
    assert '127.0.0.42' not in event_raw
    assert '127.0.0.43' not in event_raw
    assert '4.8.15.16' not in event_raw
    assert 'sensitive' not in event_raw
