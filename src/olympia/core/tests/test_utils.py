import json
from unittest import mock

from olympia.core.utils import get_version_json


def test_get_version_json():
    version = {'version': '1.0.0'}
    with mock.patch('builtins.open', mock.mock_open(read_data=json.dumps(version))):
        assert get_version_json() == version


def test_get_version_json_missing():
    with mock.patch('os.path.exists', return_value=False):
        assert get_version_json() is None


def test_get_version_json_error():
    with mock.patch('builtins.open', mock.mock_open(read_data='')):
        with mock.patch('builtins.print', mock.Mock()) as mock_print:
            assert get_version_json() is None
            mock_print.assert_called_once()
            args, _ = mock_print.call_args
            assert args[0].startswith('Error reading')
