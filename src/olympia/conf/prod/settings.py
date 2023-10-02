# ruff: noqa: F405
from olympia.lib.settings_base import *  # noqa

ALLOWED_HOSTS = [
    '.amo.prod.webservices.mozgcp.net',
    '.mozilla.org',
    '.mozilla.com',
    '.mozilla.net',
    '.mozaws.net',
]

ENGAGE_ROBOTS = True

EMAIL_URL = env.email_url('EMAIL_URL')
EMAIL_HOST = EMAIL_URL['EMAIL_HOST']
EMAIL_PORT = EMAIL_URL['EMAIL_PORT']
EMAIL_BACKEND = EMAIL_URL['EMAIL_BACKEND']
EMAIL_HOST_USER = EMAIL_URL['EMAIL_HOST_USER']
EMAIL_HOST_PASSWORD = EMAIL_URL['EMAIL_HOST_PASSWORD']

SEND_REAL_EMAIL = True

ENV = env('ENV')

API_THROTTLING = True

DOMAIN = env('DOMAIN', default='addons.mozilla.org')
SERVER_EMAIL = 'zprod@addons.mozilla.org'
SITE_URL = 'https://' + DOMAIN
INTERNAL_SITE_URL = env('INTERNAL_SITE_URL', default='https://addons.mozilla.org')
EXTERNAL_SITE_URL = env('EXTERNAL_SITE_URL', default='https://addons.mozilla.org')
SERVICES_URL = env('SERVICES_URL', default='https://services.addons.mozilla.org')
CODE_MANAGER_URL = env('CODE_MANAGER_URL', default='https://code.addons.mozilla.org')
STATIC_URL = PROD_STATIC_URL
MEDIA_URL = PROD_MEDIA_URL

SESSION_COOKIE_DOMAIN = '.%s' % DOMAIN

# Domain emails should be sent to.
INBOUND_EMAIL_DOMAIN = env('INBOUND_EMAIL_DOMAIN', default='addons.mozilla.org')

DATABASES = {
    'default': get_db_config('DATABASES_DEFAULT_URL'),
    'replica': get_db_config('DATABASES_REPLICA_URL', atomic_requests=False),
}

REPLICA_DATABASES = ['replica']

# Celery
CELERY_BROKER_CONNECTION_TIMEOUT = 0.5

ES_TIMEOUT = 60
ES_INDEXES = {k: f'{v}_{ENV}' for k, v in ES_INDEXES.items()}
ES_DEFAULT_NUM_SHARDS = 10

RECOMMENDATION_ENGINE_URL = env(
    'RECOMMENDATION_ENGINE_URL',
    default='https://taar.prod.mozaws.net/v1/api/recommendations/',
)

TAAR_LITE_RECOMMENDATION_ENGINE_URL = env(
    'TAAR_LITE_RECOMMENDATION_ENGINE_URL',
    default=('https://taarlite.prod.mozaws.net/taarlite/api/v1/addon_recommendations/'),
)

EXTENSION_WORKSHOP_URL = env(
    'EXTENSION_WORKSHOP_URL', default='https://extensionworkshop.com'
)

REMOTE_SETTINGS_API_URL = 'https://firefox.settings.services.mozilla.com/v1/'
REMOTE_SETTINGS_WRITER_URL = env(
    'REMOTE_SETTINGS_WRITER_URL', default='https://remote-settings.mozilla.org/v1/'
)
REMOTE_SETTINGS_WRITER_BUCKET = 'staging'

# See: https://bugzilla.mozilla.org/show_bug.cgi?id=1633746
BIGQUERY_AMO_DATASET = 'amo_prod'
