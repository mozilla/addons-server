import json
from unittest import mock

import pytest

from olympia.zadmin.models import Config, amo, get_config, set_config


@mock.patch.object(amo, 'config_keys')
@pytest.mark.django_db
def test_set_config(keys_mock):
    keys_mock.KEYS = ['foo']

    assert Config.objects.filter(key='foo').count() == 0
    set_config('foo', 'bar')
    assert Config.objects.get(key='foo').value == 'bar'

    # missing key should error
    with pytest.raises(AssertionError):
        set_config('key', 'value 0')

    keys_mock.KEYS = ['foo', 'key']
    # Overwrites existing values
    set_config('key', 'value 1')
    set_config('key', 'value 2')
    assert Config.objects.get(key='key').value == 'value 2'

    # with a json value
    keys_mock.KEY = 'key', json, int
    set_config(keys_mock.KEY, ['value 1', 'value 2'])

    assert Config.objects.get(key='key').value == '["value 1", "value 2"]'


@mock.patch('olympia.zadmin.models.amo.config_keys')
@mock.patch('olympia.zadmin.models.log')
@pytest.mark.django_db
def test_get_config(log_mock, keys_mock):
    # a missing key should raise
    with pytest.raises(AssertionError):
        get_config('key')
    assert log_mock.error.call_count == 0

    # if the key exists, it should work and return None
    keys_mock.KEYS = ['key']
    assert get_config('key') is None
    assert log_mock.error.call_count == 0

    # and if it has a value, that value
    Config.objects.create(key='key', value='value')
    assert get_config('key') == 'value'
    assert log_mock.error.call_count == 0

    Config.objects.filter(key='key').update(value='value 2')
    assert get_config('key') == 'value 2'
    assert log_mock.error.call_count == 0

    # and with other types of values
    Config.objects.filter(key='key').update(value='{"foo": "bar"}')
    assert get_config(('key', json, None)) == {'foo': 'bar'}

    Config.objects.filter(key='key').update(value='56786798')
    assert get_config(('key', int, 1)) == 56786798

    # similarly if the key is defined with a default
    keys_mock.KEYS = ['key', 'absent']
    assert get_config(('absent', str, 'oops')) == 'oops'
    assert log_mock.error.call_count == 0

    assert get_config(('absent', int, 42)) == 42
    assert log_mock.error.call_count == 0

    assert get_config(('absent', json, {})) == {}
    assert log_mock.error.call_count == 0

    # if the instance value is malformed, we return the default though
    Config.objects.filter(key='key').update(value='not a number')
    assert get_config(('key', int, 1)) == 1
    assert log_mock.error.call_count == 1
    assert log_mock.error.call_args[0] == (
        '[%s] config key appears to not be set correctly (%s)',
        'key',
        'not a number',
    )
    log_mock.error.reset_mock()

    Config.objects.filter(key='key').update(value=',,,')
    assert get_config(('key', json, {})) == {}
    assert log_mock.error.call_count == 1
    assert log_mock.error.call_args[0] == (
        '[%s] config key appears to not be set correctly (%s)',
        'key',
        ',,,',
    )
    log_mock.error.reset_mock()
