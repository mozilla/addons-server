# ruff: noqa: F405
"""This is the standard development settings file.

If you need to overload settings, please do so in a local_settings.py file (it
won't be tracked in git).

"""

import os
from urllib.parse import urlparse

from olympia.lib.settings_base import *  # noqa


# "production" is a named docker stage corresponding to the production image.
# when we build the production image, the stage to use is determined
# via the "DOCKER_TARGET" variable which is also passed into the image.
# So if the value is anything other than "production" we are in development mode.
DEV_MODE = DOCKER_TARGET != 'production'

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
DATA_BACKUP_SKIP = os.environ.get('DATA_BACKUP_SKIP', False)

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


if DEV_MODE:
    INSTALLED_APPS += (
        'debug_toolbar',
        'dbbackup',
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

SITE_URL = os.environ.get('OLYMPIA_SITE_URL') or 'http://localhost:8000'
DOMAIN = SERVICES_DOMAIN = urlparse(SITE_URL).netloc
ADDONS_FRONTEND_PROXY_PORT = '7000'
SERVICES_URL = SITE_URL
INTERNAL_SITE_URL = 'http://nginx'
EXTERNAL_SITE_URL = SITE_URL
STATIC_URL = '%s/static/' % EXTERNAL_SITE_URL
MEDIA_URL = '%s/user-media/' % EXTERNAL_SITE_URL

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

# When USE_FAKE_FXA_AUTH and settings.DEV_MODE are both True, we serve a fake
# authentication page, bypassing FxA. To disable this behavior, set
# USE_FAKE_FXA = False in your local settings.
# You will also need to specify `client_id` and `client_secret` in your
# local_settings.py or environment variables - you must contact the FxA team to get your
# own credentials for FxA stage.
USE_FAKE_FXA_AUTH = True

# CSP report endpoint which returns a 204 from addons-nginx in local dev.
CSP_REPORT_URI = '/csp-report'
RESTRICTED_DOWNLOAD_CSP['REPORT_URI'] = CSP_REPORT_URI

# Set CSP like we do for dev/stage/prod, but also allow GA over http + www subdomain
# for local development.
HTTP_GA_SRC = 'http://www.google-analytics.com'

CSP_CONNECT_SRC += (SITE_URL,)
CSP_FONT_SRC += (STATIC_URL,)
CSP_IMG_SRC += (MEDIA_URL, STATIC_URL, HTTP_GA_SRC)
CSP_SCRIPT_SRC += (STATIC_URL, HTTP_GA_SRC)
CSP_STYLE_SRC += (STATIC_URL,)

# Auth token required to authorize inbound email.
INBOUND_EMAIL_SECRET_KEY = 'totally-unsecure-secret-string'
# Validation key we need to send in POST response.
INBOUND_EMAIL_VALIDATION_KEY = 'totally-unsecure-validation-string'

# Sectools
CUSTOMS_API_URL = 'http://customs:10101/'
CUSTOMS_API_KEY = 'customssecret'

REMOTE_SETTINGS_IS_TEST_SERVER = True

local_settings_path = path('local_settings.py')

if not os.path.exists(local_settings_path):
    with open(local_settings_path, 'w') as file:
        file.write('# Put settings you want to overload in this file.\n')

from local_settings import *  # noqa

SITEMAP_DEBUG_AVAILABLE = True

# Recaptcha test keys from https://developers.google.com/recaptcha/docs/faq.
# Will show the widget but no captcha, verification will always pass.
RECAPTCHA_PUBLIC_KEY = '6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI'
RECAPTCHA_PRIVATE_KEY = '6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe'

ADDONS_SERVER_DOCS_URL = 'https://addons-server.readthedocs.io/en/latest'


SWAGGER_SETTINGS = {
    'USE_SESSION_AUTH': False,
    'DEEP_LINKING': True,
    'SECURITY_DEFINITIONS': {
        'Session ID': {
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header',
            'description': (
                'Use your session ID found in the sessionid cookie. See the '
                f'[docs]({ADDONS_SERVER_DOCS_URL}/topics/api/auth_internal.html). \n'
                'Format as `Session <sessionid>`'
            ),
        },
        'JWT': {
            'type': 'apiKey',
            'name': 'Authorization',
            'in': 'header',
            'description': (
                'Use JWT token. see the '
                f'[docs]({ADDONS_SERVER_DOCS_URL}/topics/api/auth.html). \n'
                'Format as `JWT <token>`'
            ),
        },
    },
    'PERSIST_AUTH': True,
}

ENABLE_ADMIN_MLBF_UPLOAD = True
