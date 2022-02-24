import os
import json

from copy import deepcopy

import pytest

from django.conf import settings

from olympia.lib.settings_base import get_sentry_release


@pytest.mark.parametrize(
    'key', ('SHARED_STORAGE', 'GUARDED_ADDONS_PATH', 'TMP_PATH', 'MEDIA_ROOT')
)
def test_base_paths_bytestring(key):
    """Make sure all relevant base paths are bytestrings.

    Filenames and filesystem paths are generally handled as byte-strings
    and we are running into various errors if they're not.

    One of many examples would be

    >>> os.path.join('path1', 'pæth2'.encode('utf-8'))
    Traceback (most recent call last):
      File "<stdin>", line 1, in <module>
      File "/usr/lib64/python2.7/posixpath.py", line 80, in join
        path += '/' + b
    UnicodeDecodeError: 'ascii' codec can't decode byte...

    See https://github.com/mozilla/addons-server/issues/3579 for context.
    """
    assert isinstance(getattr(settings, key), str)


def test_sentry_release_config():
    version_json = os.path.join(settings.ROOT, 'version.json')
    original = None

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
    before_send = settings.SENTRY_CONFIG.get('before_send')
    assert before_send
    assert settings.SENTRY_CONFIG.get('send_default_pii') is True
    event_raw = open(
        os.path.join(settings.ROOT, 'src/olympia/amo/fixtures/sentry_event.json')
    ).read()
    event = json.loads(event_raw)
    assert '@bar.com' in event_raw
    assert '172.18.0.1' in event_raw
    assert '127.0.0.42' in event_raw
    expected_request_data = deepcopy(event['payload']['request'])

    expected_frame_data = deepcopy(
        event['payload']['exception']['values'][0]['stacktrace']['frames'][3]
    )

    event = before_send(event, None)
    event_raw = json.dumps(event)
    assert '@bar.com' not in event_raw
    assert '172.18.0.1' not in event_raw
    assert '127.0.0.42' not in event_raw

    # We keep cookies, user dict
    assert event['payload']['request']['cookies']
    assert event['payload']['user']['id']

    # Email and ip_address are redacted though
    assert event['payload']['user']['email'] == '*** redacted ***'
    assert event['payload']['user']['ip_address'] == '*** redacted ***'

    # Modify old_request_data according to what we should have done and see if
    # it matches what before_send() did in reality.
    expected_request_data['env']['REMOTE_ADDR'] = '*** redacted ***'
    # Note special case for X-forwarded-for in the 'headers' dict, meant to
    # test we don't care about case.
    expected_request_data['headers']['X-forwarded-for'] = '*** redacted ***'
    assert expected_request_data == event['payload']['request']

    # Same for expected_frame_data.
    expected_frame_data['vars']['email'] = '*** redacted ***'
    expected_frame_data['vars']['some_dict']['email'] = '*** redacted ***'
    expected_frame_data['vars']['some_dict']['second_level'][1][
        'email'
    ] = '*** redacted ***'
    assert (
        expected_frame_data
        == event['payload']['exception']['values'][0]['stacktrace']['frames'][3]
    )
