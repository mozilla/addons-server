import hashlib
import functools
import itertools
from contextlib import contextmanager

from django.core.cache.backends.base import DEFAULT_TIMEOUT, BaseCache
from django.core.cache import cache, caches, _create_cache
from django.utils import translation
from django.utils.encoding import force_bytes, force_text


def make_key(key, with_locale=True, normalize=False):
    """Generate the full key for ``k``, with a prefix."""
    if with_locale:
        key = u'{key}:{lang}'.format(
            key=key, lang=translation.get_language())

    if normalize:
        return force_text(hashlib.md5(force_bytes(key)).hexdigest())
    return force_text(key)


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
        key.update(force_bytes(arg))
    return 'memoize:{prefix}:{key}'.format(prefix=prefix, key=key.hexdigest())


def memoize(prefix, timeout=60):
    """
    A simple decorator that caches into memcache, using a simple
    key based on stringing args and kwargs.
    Arguments to the method must be easily and consistently serializable
    using str(..) otherwise the cache key will be inconsistent.
    :param prefix: a prefix for the key in memcache
    :type prefix: string
    :param timeout: number of seconds to cache the key for, default 60 seconds
    :type timeout: integer
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            def wrapped_func():
                return func(*args, **kwargs)
            key = memoize_key(prefix, *args, **kwargs)
            return cache.get_or_set(key, wrapped_func, timeout=DEFAULT_TIMEOUT)
        return wrapper
    return decorator


class Message(object):
    """
    A simple class to store an item in memcache, given a key.
    """
    def __init__(self, key):
        self.key = 'message:{key}'.format(key=key)

    def delete(self):
        cache.delete(self.key)

    def save(self, message, time=60 * 5):
        cache.set(self.key, message, time)

    def get(self, delete=False):
        res = cache.get(self.key)
        if delete:
            cache.delete(self.key)
        return res


class CacheStatTracker(BaseCache):
    """A small class used to track cache calls."""
    requests_limit = 5000

    def __init__(self, location, params):
        custom_params = params.copy()
        options = custom_params['OPTIONS'].copy()

        custom_params['BACKEND'] = options.pop('ACTUAL_BACKEND')
        custom_params['OPTIONS'] = options

        # Patch back in the `location` for memcached backend to pick up.
        custom_params['LOCATION'] = location

        self._real_cache = _create_cache(
            custom_params['BACKEND'], **custom_params)

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
def assert_cache_requests(num, alias='default'):
    cache_using = caches[alias]
    cache_using.clear_log()

    yield

    executed = len(cache_using.requests_log)

    assert executed == num, "%d requests executed, %d expected" % (
        executed, num)
