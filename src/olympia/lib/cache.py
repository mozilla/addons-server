import hashlib
import functools
import itertools

from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache import cache
from django.utils import translation
from django.utils.encoding import force_bytes, force_str


def make_key(key, with_locale=True, normalize=False):
    """Generate the full key for ``k``, with a prefix."""
    if with_locale:
        key = f'{key}:{translation.get_language()}'

    if normalize:
        return force_str(hashlib.md5(force_bytes(key)).hexdigest())
    return force_str(key)


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
    return f'memoize:{prefix}:{key.hexdigest()}'


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
