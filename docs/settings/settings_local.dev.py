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

CACHE_BACKEND = 'django_pylibmc.memcached://localhost:11211?timeout=5000'
# Uncomment to disable caching:
# CACHE_BACKEND = 'dummy://'

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

# If you're not running on SSL you'll want this to be False
SESSION_COOKIE_SECURE = False
