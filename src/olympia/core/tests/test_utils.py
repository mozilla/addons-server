import json
import sys
from unittest import mock

from olympia.core.utils import get_version_json


default_version = {
    'commit': 'commit',
    'version': 'local',
    'build': 'build',
    'source': 'https://github.com/mozilla/addons-server',
}


@mock.patch.dict('os.environ', clear=True)
def test_get_version_json_defaults():
    result = get_version_json()

    assert result['commit'] == default_version['commit']
    assert result['version'] == default_version['version']
    assert result['build'] == default_version['build']
    assert result['source'] == default_version['source']


def test_get_version_json_commit():
    with mock.patch.dict('os.environ', {'DOCKER_COMMIT': 'new_commit'}):
        result = get_version_json()

    assert result['commit'] == 'new_commit'


def test_get_version_json_version():
    with mock.patch.dict('os.environ', {'DOCKER_VERSION': 'new_version'}):
        result = get_version_json()

    assert result['version'] == 'new_version'


def test_get_version_json_build():
    with mock.patch.dict('os.environ', {'DOCKER_BUILD': 'new_build'}):
        result = get_version_json()

    assert result['build'] == 'new_build'


def test_get_version_json_python():
    with mock.patch.object(sys, 'version_info') as v_info:
        v_info.major = 3
        v_info.minor = 9
        result = get_version_json()

    assert result['python'] == '3.9'


def test_get_version_json_django():
    with mock.patch('django.VERSION', (3, 2)):
        result = get_version_json()

    assert result['django'] == '3.2'


def test_get_version_json_addons_linter():
    with mock.patch('os.path.exists', return_value=True):
        with mock.patch(
            'builtins.open',
            mock.mock_open(read_data='{"dependencies": {"addons-linter": "1.2.3"}}'),
        ):
            result = get_version_json()

    assert result['addons-linter'] == '1.2.3'


def test_get_version_json_addons_linter_missing_package():
    with mock.patch('os.path.exists', return_value=True):
        with mock.patch(
            'builtins.open', mock.mock_open(read_data=json.dumps({'dependencies': {}}))
        ):
            result = get_version_json()

    assert result['addons-linter'] == ''


def test_get_version_json_addons_linter_missing_file():
    with mock.patch('os.path.exists', return_value=False):
        result = get_version_json()

    assert result['addons-linter'] == ''
