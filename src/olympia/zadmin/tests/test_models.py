import pytest

from olympia.zadmin.models import set_config, Config


@pytest.mark.django_db
def test_set_config():
    assert Config.objects.filter(key='foo').count() == 0
    set_config('foo', 'bar')
    assert Config.objects.get(key='foo').value == 'bar'

    # Overwrites existing values
    set_config('key', 'value 1')
    set_config('key', 'value 2')

    assert Config.objects.get(key='key').value == 'value 2'
