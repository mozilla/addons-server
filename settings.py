"""This is the standard development settings file.

If you need to overload settings, please do so in a local_settings.py file (it
won't be tracked in git).

"""
import os
from six.moves.urllib_parse import urlparse

from olympia.lib.settings_base import *  # noqa

WSGI_APPLICATION = 'olympia.wsgi.application'

DEBUG = True

# These apps are great during development.
INSTALLED_APPS += (
    'olympia.landfill',
)

FILESYSTEM_CACHE_ROOT = os.path.join(TMP_PATH, 'cache')

# We are setting memcached here to make sure our local setup is as close
# to our production system as possible.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
        'LOCATION': os.environ.get('MEMCACHE_LOCATION', 'localhost:11211'),
    },
}

# If you're not running on SSL you'll want this to be False.
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_DOMAIN = None

CELERY_TASK_ALWAYS_EAGER = False

# Locally we typically don't run more than 1 elasticsearch node. So we set
# replicas to zero.
ES_DEFAULT_NUM_REPLICAS = 0

SITE_URL = os.environ.get('OLYMPIA_SITE_URL') or 'http://localhost:8000'
DOMAIN = SERVICES_DOMAIN = urlparse(SITE_URL).netloc
SERVICES_URL = SITE_URL

CODE_MANAGER_URL = os.environ.get('CODE_MANAGER_URL') or 'http://localhost:3000'

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

DATABASES = {
    'default': get_db_config('DATABASES_DEFAULT_URL'),
}

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
        'redirect_url': 'http://localhost:3000/api/v3/accounts/authenticate/?config=local', # noqa
        'scope': 'profile',
    },
    'code-manager': {
        'client_id': env('CODE_MANAGER_FXA_CLIENT_ID', default='a98b671fdd3dfcea'), # noqa
        'client_secret': env(
            'CODE_MANAGER_FXA_CLIENT_SECRET',
            default='d9934865e34bed4739a2dc60046a90d09a5d8336cf92809992dec74a4cff4665'),  # noqa
        'content_host': 'https://stable.dev.lcip.org',
        'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
        'profile_host': 'https://stable.dev.lcip.org/profile/v1',
        'redirect_url': 'http://olympia.test/api/v4/accounts/authenticate/?config=code-manager', # noqa
        'scope': 'profile',
    },
}
ALLOWED_FXA_CONFIGS = ['default', 'amo', 'local', 'code-manager']

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
except ImportError:
    import warnings
    import traceback

    warnings.warn('Could not import local_settings module. {}'.format(
        traceback.format_exc()))
