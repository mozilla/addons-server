"""This is the standard development settings file.

If you need to overload settings, please do so in a local_settings.py file (it
won't be tracked in git).

"""
import os
from urllib.parse import urlparse

from olympia.lib.settings_base import *  # noqa

WSGI_APPLICATION = 'olympia.wsgi.application'

INTERNAL_ROUTES_ALLOWED = True

DEBUG = True

# These apps are great during development.
INSTALLED_APPS += (
    'olympia.landfill',
    'debug_toolbar',
)

# Override logging config to enable DEBUG logs for (almost) everything.
LOGGING['root']['level'] = logging.DEBUG
for logger in list(LOGGING['loggers'].keys()):
    if logger not in ['filtercascade', 'mohawk.util', 'post_request_task']:
        del LOGGING['loggers'][logger]

# django-debug-doolbar middleware needs to be inserted as high as possible
# but after GZip middleware
def insert_debug_toolbar_middleware(middlewares):
    ret_middleware = list(middlewares)

    for i, middleware in enumerate(ret_middleware):
        if 'GZipMiddleware' in middleware:
            ret_middleware.insert(
                i + 1, 'debug_toolbar.middleware.DebugToolbarMiddleware')
            break

    return tuple(ret_middleware)


MIDDLEWARE = insert_debug_toolbar_middleware(MIDDLEWARE)

DEBUG_TOOLBAR_CONFIG = {
    # Enable django-debug-toolbar locally, if DEBUG is True.
    'SHOW_TOOLBAR_CALLBACK': lambda request: DEBUG,
}

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
EXTERNAL_SITE_URL = SITE_URL

CODE_MANAGER_URL = (
    os.environ.get('CODE_MANAGER_URL') or 'http://localhost:3000')

ALLOWED_HOSTS = ALLOWED_HOSTS + [SERVICES_DOMAIN]

# Default AMO user id to use for tasks (from users.json fixture in zadmin).
TASK_USER_ID = 10968

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
        'client_id': env('FXA_CLIENT_ID', default='a25796da7bc73ffa'),
        'client_secret': env(
            'FXA_CLIENT_SECRET',
            default='4828af02f60a12738a79c7121b06d42b481f112dce1831440902a8412d2770c5'),  # noqa
        # fxa redirects to http://olympia.test/api/auth/authenticate-callback/
    },
    'amo': {
        'client_id': env('FXA_CLIENT_ID', default='0f95f6474c24c1dc'),
        'client_secret': env(
            'FXA_CLIENT_SECRET',
            default='ca45e503a1b4ec9e2a3d4855d79849e098da18b7dfe42b6bc76dfed420fc1d38'),  # noqa
        # fxa redirects to http://localhost:3000/fxa-authenticate
    },
    'local': {
        'client_id': env('FXA_CLIENT_ID', default='4dce1adfa7901c08'),
        'client_secret': env(
            'FXA_CLIENT_SECRET',
            default='d7d5f1148a35b12c067fb9eafafc29d35165a90f5d8b0032f1fcd37468ae49fe'),  # noqa
        # noqa fxa redirects to http://localhost:3000/api/auth/authenticate-callback/?config=local  #noqa
    },
}
FXA_CONTENT_HOST = 'https://stable.dev.lcip.org'
FXA_OAUTH_HOST = 'https://oauth-stable.dev.lcip.org/v1'
FXA_PROFILE_HOST = 'https://stable.dev.lcip.org/profile/v1'
ALLOWED_FXA_CONFIGS = ['default', 'amo', 'local']

# CSP report endpoint which returns a 204 from addons-nginx in local dev.
CSP_REPORT_URI = '/csp-report'
RESTRICTED_DOWNLOAD_CSP['REPORT_URI'] = CSP_REPORT_URI

# Allow GA over http + www subdomain in local development.
HTTP_GA_SRC = 'http://www.google-analytics.com'
CSP_IMG_SRC += (HTTP_GA_SRC,)
CSP_SCRIPT_SRC += (HTTP_GA_SRC, "'self'")

# Auth token required to authorize inbound email.
INBOUND_EMAIL_SECRET_KEY = 'totally-unsecure-secret-string'
# Validation key we need to send in POST response.
INBOUND_EMAIL_VALIDATION_KEY = 'totally-unsecure-validation-string'

# Sectools
CUSTOMS_API_URL = 'http://customs:10101/'
CUSTOMS_API_KEY = 'customssecret'
WAT_API_URL = 'http://wat:10102/'
WAT_API_KEY = 'watsecret'

KINTO_API_IS_TEST_SERVER = True

# If you have settings you want to overload, put them in a local_settings.py.
try:
    from local_settings import *  # noqa
except ImportError:
    import warnings
    import traceback

    warnings.warn('Could not import local_settings module. {}'.format(
        traceback.format_exc()))
