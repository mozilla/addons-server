from settings import *

DEBUG = True
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = DEBUG

# These apps are great during development.
INSTALLED_APPS += (
    'debug_toolbar',
    'django_extensions',
    'fixture_magic',
    'django_qunit',
)

# You want one of the caching backends.  Dummy won't do any caching, locmem is
# cleared every time you restart the server, and memcached is what we run in
# production.
# CACHE_BACKEND = 'caching.backends.memcached://localhost:11211?timeout=500'
CACHE_BACKEND = 'caching.backends.locmem://'
# Some cache is required for CSRF to work. Dummy will allow some functionality,
# but won't allow you to login.
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

# Skip indexing ES to speed things up?
SKIP_SEARCH_INDEX = False

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
SESSION_COOKIE_DOMAIN = None

# Run tasks immediately, don't try using the queue.
CELERY_ALWAYS_EAGER = True

# Disables custom routing in settings.py so that tasks actually run.
CELERY_ROUTES = {}

# paths for images, not necessary for dev
STATIC_URL = ''

# The user id to use when logging in tasks. You should set this to a user that
# exists in your site.
# TASK_USER_ID = 1
