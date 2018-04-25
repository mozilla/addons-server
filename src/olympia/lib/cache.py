import hashlib

from django.core.cache import cache
from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.utils import encoding, translation
from django.conf import settings


def make_key(key=None, with_locale=True):
    """Generate the full key for ``k``, with a prefix."""
    key = encoding.smart_bytes('{prefix}:{key}'.format(
        prefix=settings.KEY_PREFIX,
        key=key))

    if with_locale:
        key += encoding.smart_bytes(translation.get_language())
    # memcached keys must be < 250 bytes and w/o whitespace, but it's nice
    # to see the keys when using locmem.
    return hashlib.md5(key).hexdigest()


def cached(function, key, duration=DEFAULT_TIMEOUT):
    """Check if `key` is in the cache, otherwise call `function` and cache
    the result.
    """
    cache_key = make_key(key)

    value = cache.get(cache_key)
    if value is None:
        value = function()
        cache.set(cache_key, value, duration)
    return value
