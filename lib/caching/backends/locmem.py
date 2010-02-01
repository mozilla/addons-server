from django.core.cache.backends import locmem


# Add infinite timeout support to the locmem backend.  Useful for testing.
class CacheClass(locmem.CacheClass):

    def add(self, key, value, timeout=None):
        if timeout == 0:
            timeout = Infinity
        return super(CacheClass, self).add(key, value, timeout)

    def set(self, key, value, timeout=None):
        if timeout == 0:
            timeout = Infinity
        return super(CacheClass, self).set(key, value, timeout)


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
