from django.conf import settings
from django.core.cache import parse_backend_uri
from werkzeug.contrib import cache as wcache


BACKENDS = {
    'memcached': wcache.MemcachedCache,
    'locmem': wcache.SimpleCache,
    'file': wcache.FileSystemCache,
    'dummy': wcache.NullCache,
}


# Set up the cache using Django's URI scheme.
scheme, host, params = parse_backend_uri(settings.CACHE_BACKEND)

if host:
    cache = BACKENDS[scheme](host.split(';'), **params)
else:
    cache = BACKENDS[scheme](**params)

cache.scheme = scheme


class CacheFixer(cache.__class__):

    def get(self, key, default=None):
        # Werkzeug's get doesn't have a default.
        val = super(CacheFixer, self).get(key)
        return default if val is None else val

    # Werkzeug's non-memcached backends don't handle a timeout of 0 correctly.
    # In memcached, the object is cached forever, while the other backends will
    # expire it immediately.  We introduce Infinity to cache things forever.
    if not isinstance(cache, wcache.MemcachedCache):

        def add(self, key, value, timeout=None):
            if timeout == 0:
                timeout = Infinity
            return super(CacheFixer, self).add(key, value, timeout)

        def set(self, key, value, timeout=None):
            if timeout == 0:
                timeout = Infinity
            return super(CacheFixer, self).set(key, value, timeout)


cache.__class__ = CacheFixer


class _Infinity(object):
    """Always compares greater than numbers."""

    def __radd__(self, _):
        return self

    def __cmp__(self, o):
        return 0 if self is o else 1

    def __repr__(self):
        return 'Infinity'

Infinity = _Infinity()
del _Infinity
