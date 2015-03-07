"""This is the standard development settings file.

If you need to overload settings, please do so in a local_settings.py file (it
won't be tracked in git).

"""
import os

from lib.settings_base import *  # noqa

DEBUG = True
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = DEBUG

# These apps are great during development.
INSTALLED_APPS += (
    'django_extensions',
    'landfill',
)

# Using locmem deadlocks in certain scenarios. This should all be fixed,
# hopefully, in Django1.7. At that point, we may try again, and remove this to
# not require memcache installation for newcomers.
# A failing scenario is:
# 1/ log in
# 2/ click on "Submit a new addon"
# 3/ click on "I accept this Agreement" => request never ends
#
# If this is changed back to locmem, make sure to use it from "caching" (by
# default in Django for locmem, a timeout of "0" means "don't cache it", while
# on other backends it means "cache forever"):
#      'BACKEND': 'caching.backends.locmem.LocMemCache'
CACHES = {
    'default': {
        'BACKEND': 'caching.backends.memcached.MemcachedCache',
        'LOCATION': os.environ.get('MEMCACHE_LOCATION', 'localhost:11211'),
    }
}

HAS_SYSLOG = False  # syslog is used if HAS_SYSLOG and NOT DEBUG.

# If you're not running on SSL you'll want this to be False.
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_DOMAIN = None

# Disables custom routing in settings.py so that tasks actually run.
CELERY_ALWAYS_EAGER = True
CELERY_ROUTES = {}

# Disable timeout code during development because it uses the signal module
# which can only run in the main thread. Celery uses threads in dev.
VALIDATOR_TIMEOUT = -1

# If you want to allow self-reviews for add-ons/apps, then enable this.
# In production we do not want to allow this.
ALLOW_SELF_REVIEWS = True

# Assuming you did `npm install` (and not `-g`) like you were supposed to, this
# will be the path to the `stylus` and `lessc` executables.
STYLUS_BIN = path('node_modules/stylus/bin/stylus')
LESS_BIN = path('node_modules/less/bin/lessc')
CLEANCSS_BIN = path('node_modules/clean-css/bin/cleancss')
UGLIFY_BIN = path('node_modules/uglify-js/bin/uglifyjs')

# Locally we typically don't run more than 1 elasticsearch node. So we set
# replicas to zero.
ES_DEFAULT_NUM_REPLICAS = 0

SITE_URL = 'http://localhost:8000'
SERVICES_DOMAIN = 'localhost:8000'
SERVICES_URL = 'http://%s' % SERVICES_DOMAIN

VALIDATE_ADDONS = False

ADDON_COLLECTOR_ID = 1

# Default AMO user id to use for tasks (from users.json fixture in zadmin).
TASK_USER_ID = 10968


# If you have settings you want to overload, put them in a local_settings.py.
try:
    from local_settings import *  # noqa
except ImportError:
    pass
