from settings import *


DATABASES = {
    'default': {
        'NAME': 'zamboni',
        'ENGINE': 'django.db.backends.mysql',
        'USER': 'jbalogh',
        'PASSWORD': 'xxx',
        'OPTIONS':  {'init_command': 'SET storage_engine=InnoDB'},
    },
}

# For debug toolbar.
MIDDLEWARE_CLASSES += ('debug_toolbar.middleware.DebugToolbarMiddleware',)
INTERNAL_IPS = ('127.0.0.1',)
INSTALLED_APPS += ('debug_toolbar',)

CACHE_BACKEND = 'memcached://localhost:11211'
CACHE_DURATION = 500

DEBUG = True
