"""This is the standard development settings file.

If you need to overload settings, please do so in a local_settings.py file (it
won't be tracked in git).

"""
import os
from urlparse import urlparse

from olympia.lib.settings_base import *  # noqa

WSGI_APPLICATION = 'olympia.wsgi.application'

DEBUG = True

# These apps are great during development.
INSTALLED_APPS += (
    'olympia.landfill',
)

FILESYSTEM_CACHE_ROOT = os.path.join(TMP_PATH, 'cache')

# Disable cache-machine locally and in tests to prepare for its removal.
CACHE_MACHINE_ENABLED = False

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
    },
    'filesystem': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': FILESYSTEM_CACHE_ROOT,
    }
}

# If you're not running on SSL you'll want this to be False.
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_DOMAIN = None

CELERY_TASK_ALWAYS_EAGER = False

# Assuming you did `npm install` (and not `-g`) like you were supposed to, this
# will be the path to the `lessc` executable.
LESS_BIN = os.getenv('LESS_BIN', path('node_modules/less/bin/lessc'))
CLEANCSS_BIN = os.getenv(
    'CLEANCSS_BIN',
    path('node_modules/clean-css-cli/bin/cleancss'))
UGLIFY_BIN = os.getenv(
    'UGLIFY_BIN',
    path('node_modules/uglify-js/bin/uglifyjs'))
ADDONS_LINTER_BIN = os.getenv(
    'ADDONS_LINTER_BIN',
    path('node_modules/addons-linter/bin/addons-linter'))

# Locally we typically don't run more than 1 elasticsearch node. So we set
# replicas to zero.
ES_DEFAULT_NUM_REPLICAS = 0

SITE_URL = os.environ.get('OLYMPIA_SITE_URL') or 'http://localhost:8000'
SERVICES_DOMAIN = urlparse(SITE_URL).netloc
SERVICES_URL = SITE_URL

ALLOWED_HOSTS = ALLOWED_HOSTS + [SERVICES_DOMAIN]

# Default AMO user id to use for tasks (from users.json fixture in zadmin).
TASK_USER_ID = 10968

# Set to True if we're allowed to use X-SENDFILE.
XSENDFILE = False

ALLOW_SELF_REVIEWS = True

AES_KEYS = {
    'api_key:secret': os.path.join(
        ROOT, 'src', 'olympia', 'api', 'tests', 'assets', 'test-api-key.txt'),
}

CORS_ENDPOINT_OVERRIDES = cors_endpoint_overrides(
    ['localhost:3000', 'olympia.test']
)

# FxA config for local development only.
FXA_CONFIG = {
    'default': {
        'client_id': env('FXA_CLIENT_ID', default='f336377c014eacf0'),
        'client_secret': env(
            'FXA_CLIENT_SECRET',
            default='5a36054059674b09ea56709c85b862c388f2d493d735070868ae8f476e16a80d'),  # noqa
        'content_host': 'https://stable.dev.lcip.org',
        'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
        'profile_host': 'https://stable.dev.lcip.org/profile/v1',
        'redirect_url': 'http://olympia.test/api/v3/accounts/authenticate/',
        'scope': 'profile',
    },
    'amo': {
        'client_id': env('FXA_CLIENT_ID', default='0f95f6474c24c1dc'),
        'client_secret': env(
            'FXA_CLIENT_SECRET',
            default='ca45e503a1b4ec9e2a3d4855d79849e098da18b7dfe42b6bc76dfed420fc1d38'),  # noqa
        'content_host': 'https://stable.dev.lcip.org',
        'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
        'profile_host': 'https://stable.dev.lcip.org/profile/v1',
        'redirect_url': 'http://localhost:3000/fxa-authenticate',
        'scope': 'profile',
    },
    'local': {
        'client_id': env('FXA_CLIENT_ID', default='1778aef72d1adfb3'),
        'client_secret': env(
            'FXA_CLIENT_SECRET',
            default='3feebe3c009c1a0acdedd009f3530eae2b88859f430fa8bb951ea41f2f859b18'),  # noqa
        'content_host': 'https://stable.dev.lcip.org',
        'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
        'profile_host': 'https://stable.dev.lcip.org/profile/v1',
        'redirect_url': 'http://localhost:3000/api/v3/accounts/authenticate/',
        'scope': 'profile',
    },
}
ALLOWED_FXA_CONFIGS = ['default', 'amo', 'local']

# CSP report endpoint which returns a 204 from addons-nginx in local dev.
CSP_REPORT_URI = '/csp-report'

# Allow GA over http + www subdomain in local development.
HTTP_GA_SRC = 'http://www.google-analytics.com'
CSP_IMG_SRC += (HTTP_GA_SRC,)
CSP_SCRIPT_SRC += (HTTP_GA_SRC, "'self'")

# Auth token required to authorize inbound email.
INBOUND_EMAIL_SECRET_KEY = 'totally-unsecure-secret-string'
# Validation key we need to send in POST response.
INBOUND_EMAIL_VALIDATION_KEY = 'totally-unsecure-validation-string'

# If you have settings you want to overload, put them in a local_settings.py.
try:
    from local_settings import *  # noqa
except ImportError as exc:
    import warnings
    import traceback

    warnings.warn('Could not import local_settings module. {}'.format(
        traceback.format_exc()))
