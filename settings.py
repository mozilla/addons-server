"""This is the standard development settings file.

If you need to overload settings, please do so in a local_settings.py file (it
won't be tracked in git).

"""
from lib.settings_base import *  # noqa

DEBUG = True
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = DEBUG

# These apps are great during development.
INSTALLED_APPS += (
    'django_extensions',
)

# Here we use the LocMemCache backend from cache-machine, as it interprets the
# "0" timeout parameter of ``cache``  in the same way as the Memcached backend:
# as infinity. Django's LocMemCache backend interprets it as a "0 seconds"
# timeout (and thus doesn't cache at all).
CACHES = {
    'default': {
        'BACKEND': 'caching.backends.locmem.LocMemCache',
        'LOCATION': 'olympia',
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
# Overload in local_settings.py to run elasticsearch related tests.
RUN_ES_TESTS = False

SITE_URL = 'http://localhost:8000/'
SERVICES_DOMAIN = 'localhost:8000'
SERVICES_URL = 'http://%s' % SERVICES_DOMAIN

VALIDATE_ADDONS = False

ADDON_COLLECTOR_ID = 1


# If you have settings you want to overload, put them in a local_settings.py.
try:
    from local_settings import *  # noqa
except ImportError:
    pass
