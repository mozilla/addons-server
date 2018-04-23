from contextlib import contextmanager

from django.core import cache as django_cache
from django.core.cache import _create_cache
from django.core.cache.backends.base import BaseCache


class CacheStatTracker(BaseCache):
    """A small class used to track cache calls."""
    requests_limit = 5000

    def __init__(self, location, params):
        actual_backend = params['OPTIONS'].pop('ACTUAL_BACKEND')

        self._real_cache = _create_cache(actual_backend, **params)

        self.requests_log = []
        self._setup_proxies()

    def __repr__(self):
        return str("<CacheStatTracker for %s>") % repr(self._real_cache)

    def __contains__(self, key):
        return self._real_cache.__contains__(key)

    def __getattr__(self, name):
        return getattr(self._real_cache, name)

    def _proxy(self, name):
        def _real_proxy(*args, **kwargs):
            self.requests_log.append({
                'name': name,
                'args': args,
                'kwargs': kwargs,
            })
            return getattr(self._real_cache, name)(*args, **kwargs)
        return _real_proxy

    def _setup_proxies(self):
        mappings = (
            'add', 'get', 'set', 'delete', 'clear', 'has_key', 'incr', 'decr',
            'get_many', 'set_many', 'delete_many')

        for name in mappings:
            setattr(self, name, self._proxy(name))

    def clear_log(self):
        self.requests_log = []


@contextmanager
def assert_cache_requests(num):
    cache_using = django_cache.caches['default']
    cache_using.clear_log()

    yield

    executed = len(cache_using.requests_log)

    assert executed == num, "%d requests executed, %d expected" % (
        executed, num,
    )
