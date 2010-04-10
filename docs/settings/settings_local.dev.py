from settings import *


DATABASES = {
    'default': {
        'NAME': 'zamboni',
        'ENGINE': 'django.db.backends.mysql',
        'USER': 'jbalogh',
        'PASSWORD': 'xxx',
        'OPTIONS':  {'init_command': 'SET storage_engine=InnoDB'},
        'TEST_CHARSET': 'utf8',
        'TEST_COLLATION': 'utf8_general_ci',
    },
}

# For debug toolbar.
MIDDLEWARE_CLASSES += ('debug_toolbar.middleware.DebugToolbarMiddleware',)
INTERNAL_IPS = ('127.0.0.1',)
INSTALLED_APPS += ('debug_toolbar',)

CACHE_BACKEND = 'caching.backends.memcached://localhost:11211?timeout=500'

DEBUG = True

DEBUG_PROPAGATE_EXCEPTIONS = DEBUG

# If you're not running on SSL you'll want this to be False
SESSION_COOKIE_SECURE = False
