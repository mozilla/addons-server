from django.core.cache.backends import memcached
from django.utils.encoding import smart_str


# Add infinite timeout support to the memcached backend.
class CacheClass(memcached.CacheClass):

    def add(self, key, value, timeout=None):
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        if timeout is None:
            timeout = self.default_timeout
        return self._cache.add(smart_str(key), value, timeout)

    def set(self, key, value, timeout=None):
        if isinstance(value, unicode):
            value = value.encode('utf-8')
        if timeout is None:
            timeout = self.default_timeout
        return self._cache.set(smart_str(key), value, timeout)
