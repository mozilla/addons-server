# ruff: noqa: F405
from olympia.lib.settings_base import *  # noqa


ENGAGE_ROBOTS = False

EMAIL_URL = env.email_url('EMAIL_URL')
EMAIL_HOST = EMAIL_URL['EMAIL_HOST']
EMAIL_PORT = EMAIL_URL['EMAIL_PORT']
EMAIL_BACKEND = EMAIL_URL['EMAIL_BACKEND']
EMAIL_HOST_USER = EMAIL_URL['EMAIL_HOST_USER']
EMAIL_HOST_PASSWORD = EMAIL_URL['EMAIL_HOST_PASSWORD']

ENV = env('ENV')

API_THROTTLING = True

DOMAIN = env('DOMAIN', default='addons.allizom.org')
SERVICES_DOMAIN = env('SERVICES_DOMAIN', default='services.addons.allizom.org')
SERVER_EMAIL = 'zstage@addons.mozilla.org'
SITE_URL = 'https://' + DOMAIN
INTERNAL_SITE_URL = env('INTERNAL_SITE_URL', default='https://addons.allizom.org')
EXTERNAL_SITE_URL = env('EXTERNAL_SITE_URL', default='https://addons.allizom.org')
SERVICES_URL = 'https://' + SERVICES_DOMAIN
CODE_MANAGER_URL = env('CODE_MANAGER_URL', default='https://code.addons.allizom.org')
STATIC_URL = '%s/static-server/' % EXTERNAL_SITE_URL
MEDIA_URL = '%s/user-media/' % EXTERNAL_SITE_URL

CSP_FONT_SRC += (STATIC_URL,)
# CSP_IMG_SRC already contains 'self', but we could be on reviewers or admin
# domain and want to load things from the regular domain.
CSP_IMG_SRC += (MEDIA_URL, STATIC_URL)
CSP_SCRIPT_SRC += (STATIC_URL,)
CSP_STYLE_SRC += (STATIC_URL,)

SESSION_COOKIE_DOMAIN = '.%s' % DOMAIN

# Domain emails should be sent to.
INBOUND_EMAIL_DOMAIN = env('INBOUND_EMAIL_DOMAIN', default='addons.allizom.org')

DATABASES = {
    'default': get_db_config('DATABASES_DEFAULT_URL'),
    'replica': get_db_config('DATABASES_REPLICA_URL', atomic_requests=False),
}

REPLICA_DATABASES = ['replica']

# Celery
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# Update the logger name used for mozlog
LOGGING['formatters']['json']['logger_name'] = 'http_app_addons_stage'

ES_TIMEOUT = 60
ES_INDEXES = {k: f'{v}_{ENV}' for k, v in ES_INDEXES.items()}

ALLOW_SELF_REVIEWS = True

FXA_CONFIG = {
    **FXA_CONFIG,
    'local': {
        'client_id': env('DEVELOPMENT_FXA_CLIENT_ID'),
        'client_secret': env('DEVELOPMENT_FXA_CLIENT_SECRET'),
        # fxa redirects to http://localhost:3000/api/auth/authenticate-callback/?config=local  # noqa
    },
}

TAAR_LITE_RECOMMENDATION_ENGINE_URL = env(
    'TAAR_LITE_RECOMMENDATION_ENGINE_URL',
    default=('https://taarlite.prod.mozaws.net/taarlite/api/v1/addon_recommendations/'),
)

REMOTE_SETTINGS_API_URL = 'https://firefox.settings.services.allizom.org/v1/'
REMOTE_SETTINGS_WRITER_URL = env(
    'REMOTE_SETTINGS_WRITER_URL', default='https://remote-settings.allizom.org/v1/'
)
REMOTE_SETTINGS_WRITER_BUCKET = 'staging'

CINDER_QUEUE_PREFIX = 'amo-stage-'
