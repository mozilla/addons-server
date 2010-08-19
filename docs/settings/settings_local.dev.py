from settings import *

DEBUG = True
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = DEBUG

# These apps are great during development.
INSTALLED_APPS += (
    'debug_toolbar',
    'django_extensions',
    'fixture_magic',
)

# You want one of the caching backends.  Dummy won't do any caching, locmem is
# cleared every time you restart the server, and memcached is what we run in
# production.
# CACHE_BACKEND = 'caching.backends.memcached://localhost:11211?timeout=500'
# CACHE_BACKEND = 'caching.backends.locmem://'
CACHE_BACKEND = 'dummy://'

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


LOG_LEVEL = logging.DEBUG
HAS_SYSLOG = False

# For debug toolbar.
if DEBUG:
    INTERNAL_IPS = ('127.0.0.1',)
    MIDDLEWARE_CLASSES += ('debug_toolbar.middleware.DebugToolbarMiddleware',)
    DEBUG_TOOLBAR_CONFIG = {
        'HIDE_DJANGO_SQL': False,
        'INTERCEPT_REDIRECTS': False,
    }

# If you're not running on SSL you'll want this to be False.
SESSION_COOKIE_SECURE = False

# Run tasks immediately, don't try using the queue.
CELERY_ALWAYS_EAGER = True
