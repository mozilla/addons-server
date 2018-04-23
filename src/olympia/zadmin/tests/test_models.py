import pytest

from django.core.cache import cache

from olympia.zadmin.models import set_config, Config
from olympia.amo.tests.cache_helpers import assert_cache_requests


@pytest.mark.django_db
def test_set_config():
    assert Config.objects.filter(key='foo').count() == 0
    set_config('foo', 'bar')
    assert Config.objects.get(key='foo').value == 'bar'

    # Overwrites existing values
    set_config('key', 'value 1')
    set_config('key', 'value 2')

    assert Config.objects.get(key='key').value == 'value 2'


def test_assert_cache_requests_helper():
    with assert_cache_requests(1):
        cache.get('foobar')

    with assert_cache_requests(2):
        cache.set('foobar', 'key')
        assert cache.get('foobar') == 'key'
