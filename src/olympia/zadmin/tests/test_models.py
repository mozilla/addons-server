from unittest import mock

import pytest

from olympia.zadmin.models import Config, get_config, set_config


@pytest.mark.django_db
def test_set_config():
    assert Config.objects.filter(key='foo').count() == 0
    set_config('foo', 'bar')
    assert Config.objects.get(key='foo').value == 'bar'

    # Overwrites existing values
    set_config('key', 'value 1')
    set_config('key', 'value 2')

    assert Config.objects.get(key='key').value == 'value 2'


@mock.patch('olympia.zadmin.models.log')
@pytest.mark.django_db
def test_get_config(log_mock):
    Config.objects.create(key='key', value='value')
    assert get_config('key') == 'value'
    assert log_mock.error.call_count == 0

    Config.objects.filter(key='key').update(value='value 2')
    assert get_config('key') == 'value 2'
    assert log_mock.error.call_count == 0

    assert get_config('absent') is None
    # Absence is not an error, just triggers the default.
    assert log_mock.error.call_count == 0

    assert get_config('absent', default='oops') == 'oops'
    assert log_mock.error.call_count == 0

    Config.objects.filter(key='key').update(value='{"foo": "bar"}')
    assert get_config('key', json_value=True) == {'foo': 'bar'}

    Config.objects.filter(key='key').update(value='56786798')
    assert get_config('key', int_value=True) == 56786798

    Config.objects.filter(key='key').update(value='not a number')
    assert get_config('key', int_value=True, default=1) == 1
    assert log_mock.error.call_count == 1
    assert log_mock.error.call_args[0] == (
        '[%s] config key appears to not be set correctly (%s)',
        'key',
        'not a number',
    )
    log_mock.error.reset_mock()

    Config.objects.filter(key='key').update(value=',,,')
    assert get_config('key', json_value=True, default={}) == {}
    assert log_mock.error.call_count == 1
    assert log_mock.error.call_args[0] == (
        '[%s] config key appears to not be set correctly (%s)',
        'key',
        ',,,',
    )
    log_mock.error.reset_mock()

    assert get_config('absent', default=42, int_value=True) == 42
    assert log_mock.error.call_count == 0
    assert get_config('absent', default='{}', json_value=True) == {}
    assert log_mock.error.call_count == 0

    # It's the caller responsibility to provide a sensible default value
    log_mock.error.reset_mock()
    assert get_config('absent', default='oops', int_value=True) == 'oops'
    assert log_mock.error.call_count == 1
    assert log_mock.error.call_args[0] == (
        '[%s] config key appears to not be set correctly (%s)',
        'absent',
        'oops',
    )

    log_mock.error.reset_mock()
    assert get_config('absent', default='oops', json_value=True) == 'oops'
    assert log_mock.error.call_count == 1
    assert log_mock.error.call_args[0] == (
        '[%s] config key appears to not be set correctly (%s)',
        'absent',
        'oops',
    )
