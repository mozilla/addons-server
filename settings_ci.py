from settings import *  # noqa

LOG_LEVEL = logging.ERROR

CACHES = {
    'default': {
        'BACKEND': 'caching.backends.memcached.MemcachedCache',
        'LOCATION': 'localhost:11211',
    }
}
