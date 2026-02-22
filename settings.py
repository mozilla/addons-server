# ruff: noqa: F405
"""This is the standard development settings file.

If you need to overload settings, please do so in a local_settings.py file (it
won't be tracked in git).

"""

import os
from copy import deepcopy
from urllib.parse import urlparse

from olympia.core.utils import get_version_json
from olympia.lib.settings_base import *  # noqa


# Any target other than "production" is considered a development target.
DEV_MODE = TARGET != 'production'

HOST_UID = os.environ.get('HOST_UID')

WSGI_APPLICATION = 'olympia.wsgi.application'

INTERNAL_ROUTES_ALLOWED = True

# Always
SERVE_STATIC_FILES = True

# These apps are great during development.
INSTALLED_APPS += ('olympia.landfill',)

DBBACKUP_STORAGE = 'django.core.files.storage.FileSystemStorage'

DBBACKUP_CONNECTOR_MAPPING = {
    'olympia.core.db.mysql': 'dbbackup.db.mysql.MysqlDumpConnector',
}
SKIP_DATA_SEED = os.environ.get('SKIP_DATA_SEED', False)

# Override logging config to enable DEBUG logs for (almost) everything.
LOGGING['root']['level'] = logging.DEBUG
for logger in list(LOGGING['loggers'].keys()):
    if logger not in ['filtercascade', 'mohawk.util', 'post_request_task']:
        # It is important to keep the loggers configured in `settings_base.py`
        # so we only update the level below:
        LOGGING['loggers'][logger]['level'] = logging.DEBUG


# django-debug-doolbar middleware needs to be inserted as high as possible
# but after GZip middleware
def insert_debug_toolbar_middleware(middlewares):
    ret_middleware = list(middlewares)

    for i, middleware in enumerate(ret_middleware):
        if 'GZipMiddleware' in middleware:
            ret_middleware.insert(
                i + 1, 'debug_toolbar.middleware.DebugToolbarMiddleware'
            )
            break

    return tuple(ret_middleware)


# We can only add these dependencies if we have development dependencies
if os.environ.get('OLYMPIA_DEPS', '') == 'development':
    INSTALLED_APPS += (
        'debug_toolbar',
        'dbbackup',
        'django_model_info.apps.DjangoModelInfoConfig',
    )
    MIDDLEWARE = insert_debug_toolbar_middleware(MIDDLEWARE)

DEBUG_TOOLBAR_CONFIG = {
    # Enable django-debug-toolbar locally, if DEBUG is True.
    'SHOW_TOOLBAR_CALLBACK': lambda request: DEBUG,
}

FILESYSTEM_CACHE_ROOT = os.path.join(TMP_PATH, 'cache')

# If you're not running on SSL you'll want this to be False.
SESSION_COOKIE_SECURE = False
SESSION_COOKIE_DOMAIN = None
WAFFLE_SECURE = False

CELERY_TASK_ALWAYS_EAGER = False

# Locally we typically don't run more than 1 elasticsearch node. So we set
# replicas to zero.
ES_DEFAULT_NUM_REPLICAS = 0

SITE_URL = env('SITE_URL')

DOMAIN = SERVICES_DOMAIN = urlparse(SITE_URL).netloc
ADDONS_FRONTEND_PROXY_PORT = '7000'
SERVICES_URL = SITE_URL
INTERNAL_SITE_URL = 'http://nginx'
EXTERNAL_SITE_URL = SITE_URL
STATIC_URL = EXTERNAL_SITE_URL + STATIC_URL_PREFIX
MEDIA_URL = EXTERNAL_SITE_URL + MEDIA_URL_PREFIX

ALLOWED_HOSTS = ALLOWED_HOSTS + [SERVICES_DOMAIN, 'nginx', '127.0.0.1']

# Default AMO user id to use for tasks (from users.json fixture in zadmin).
TASK_USER_ID = 10968

ALLOW_SELF_REVIEWS = True

AES_KEYS = {
    'api_key:secret': os.path.join(
        ROOT, 'src', 'olympia', 'api', 'tests', 'assets', 'test-api-key.txt'
    ),
}

DATABASES = {
    'default': get_db_config('DATABASES_DEFAULT_URL'),
}

FXA_CONTENT_HOST = 'https://accounts.stage.mozaws.net'
FXA_OAUTH_HOST = 'https://oauth.stage.mozaws.net/v1'
FXA_PROFILE_HOST = 'https://profile.stage.mozaws.net/v1'

# Set CSP like we do for dev/stage/prod, but also allow GA over http + www subdomain
# for local development.
HTTP_GA_SRC = 'http://www.google-analytics.com'

# we want to be able to test the settings_base without these overrides interfering
CONTENT_SECURITY_POLICY = deepcopy(CONTENT_SECURITY_POLICY)
CONTENT_SECURITY_POLICY['DIRECTIVES']['connect-src'] += (SITE_URL,)
CONTENT_SECURITY_POLICY['DIRECTIVES']['font-src'] += (STATIC_URL,)
CONTENT_SECURITY_POLICY['DIRECTIVES']['img-src'] += (MEDIA_URL, STATIC_URL, HTTP_GA_SRC)
CONTENT_SECURITY_POLICY['DIRECTIVES']['script-src'] += (STATIC_URL, HTTP_GA_SRC)
CONTENT_SECURITY_POLICY['DIRECTIVES']['style-src'] += (STATIC_URL,)
# CSP report endpoint which returns a 204 from addons-nginx in local dev.
CONTENT_SECURITY_POLICY['DIRECTIVES']['report-uri'] = '/csp-report'

# Auth token required to authorize inbound email.
INBOUND_EMAIL_SECRET_KEY = 'totally-unsecure-secret-string'
# Validation key we need to send in POST response.
INBOUND_EMAIL_VALIDATION_KEY = 'totally-unsecure-validation-string'

# Sectools
CUSTOMS_API_URL = 'http://customs:10101/'
CUSTOMS_API_KEY = 'customssecret'

REMOTE_SETTINGS_IS_TEST_SERVER = True

try:
    from local_settings import *  # noqa
except ImportError:
    pass

SITEMAP_DEBUG_AVAILABLE = True

# Recaptcha test keys from https://developers.google.com/recaptcha/docs/faq.
# Will show the widget but no captcha, verification will always pass.
RECAPTCHA_PUBLIC_KEY = '6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI'
RECAPTCHA_PRIVATE_KEY = '6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe'

ADDONS_SERVER_DOCS_URL = 'https://addons-server.readthedocs.io/en/latest'

ENABLE_ADMIN_MLBF_UPLOAD = True


# Use dev mode if we are on a non production imqage and debug is enabled.
if get_version_json().get('target') != 'production' and DEBUG:
    DJANGO_VITE = {
        'default': {
            'dev_mode': True,
            'static_url_prefix': 'bundle',
        }
    }

MEMCACHE_MIN_SERVER_COUNT = 1

GOOGLE_APPLICATION_CREDENTIALS_BIGQUERY = env(
    'GOOGLE_APPLICATION_CREDENTIALS_BIGQUERY',
    # Set default path to the path explicitly gitignored.
    default=path('private/google-application-credentials.json'),
)

CINDER_SERVER_URL = 'https://mozilla-staging.cinderapp.com/api/v1/'
