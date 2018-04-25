import functools
import hashlib
import itertools
import re
import uuid
from contextlib import contextmanager

from django.conf import settings
from django.core.cache import cache
from django.core import cache as django_cache
from django.core.cache import _create_cache
from django.core.cache.backends.base import BaseCache


def memoize_key(prefix, *args, **kwargs):
    """
    For a prefix and arguments returns a key suitable for use in memcache.
    Used by memoize.

    :param prefix: a prefix for the key in memcache
    :type param: string
    :param args: arguments to be str()'d to form the key
    :type args: list
    :param kwargs: arguments to be str()'d to form the key
    :type kwargs: list
    """
    key = hashlib.md5()
    for arg in itertools.chain(args, sorted(kwargs.items())):
        key.update(str(arg))
    return '%s:memoize:%s:%s' % (settings.CACHE_PREFIX,
                                 prefix, key.hexdigest())


def memoize_get(prefix, *args, **kwargs):
    """
    Returns the content of the cache.

    :param prefix: a prefix for the key in memcache
    :type prefix: string
    :param args: arguments to be str()'d to form the key
    :type args: list
    :param kwargs: arguments to be str()'d to form the key
    :type kwargs: list
    """
    return cache.get(memoize_key(prefix, *args, **kwargs))


def memoize(prefix, time=60):
    """
    A simple decorator that caches into memcache, using a simple
    key based on stringing args and kwargs.

    Arguments to the method must be easily and consistently serializable
    using str(..) otherwise the cache key will be inconsistent.

    :param prefix: a prefix for the key in memcache
    :type prefix: string
    :param time: number of seconds to cache the key for, default 60 seconds
    :type time: integer
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = memoize_key(prefix, *args, **kwargs)
            data = cache.get(key)
            if data is not None:
                return data
            data = func(*args, **kwargs)
            cache.set(key, data, time)
            return data
        return wrapper
    return decorator


class Message:
    """
    A simple class to store an item in memcache, given a key.
    """
    def __init__(self, key):
        self.key = '%s:message:%s' % (settings.CACHE_PREFIX, key)

    def delete(self):
        cache.delete(self.key)

    def save(self, message, time=60 * 5):
        cache.set(self.key, message, time)

    def get(self, delete=False):
        res = cache.get(self.key)
        if delete:
            cache.delete(self.key)
        return res


class Token:
    """
    A simple token stored in the cache.
    """
    _well_formed = re.compile('^[a-z0-9-]+$')

    def __init__(self, token=None, data=True):
        if token is None:
            token = str(uuid.uuid4())
        self.token = token
        self.data = data

    def cache_key(self):
        assert self.token, 'No token value set.'
        return '%s:token:%s' % (settings.CACHE_PREFIX, self.token)

    def save(self, time=60):
        cache.set(self.cache_key(), self.data, time)

    def well_formed(self):
        return self._well_formed.match(self.token)

    @classmethod
    def valid(cls, key, data=True):
        """Checks that the token is valid."""
        token = cls(key)
        if not token.well_formed():
            return False
        result = cache.get(token.cache_key())
        if result is not None:
            return result == data
        return False

    @classmethod
    def pop(cls, key, data=True):
        """Checks that the token is valid and deletes it."""
        token = cls(key)
        if not token.well_formed():
            return False
        result = cache.get(token.cache_key())
        if result is not None:
            if result == data:
                cache.delete(token.cache_key())
                return True
        return False


class CacheStatTracker(BaseCache):
    """A small class used to track cache calls."""
    requests_limit = 5000

    def __init__(self, location, params):
        # Do a .copy() dance to avoid modifying `OPTIONS` in the actual
        # settings object.
        options = params['OPTIONS'].copy()
        actual_backend = options.pop('ACTUAL_BACKEND')
        params['OPTIONS'] = options

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
