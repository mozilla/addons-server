from olympia.lib.settings_base import *  # noqa


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
CDN_HOST = 'https://addons.cdn.mozilla.net'
STATIC_URL = PROD_STATIC_URL
MEDIA_URL = PROD_MEDIA_URL
# user_media_url('addons') will use ADDONS_URL setting if present to build URLs
# to xpi files. We want those on the dedicated CDN domain.
ADDONS_URL = '%s/user-media/addons/' % CDN_HOST

SESSION_COOKIE_DOMAIN = '.%s' % DOMAIN

# Domain emails should be sent to.
INBOUND_EMAIL_DOMAIN = env('INBOUND_EMAIL_DOMAIN', default='addons.mozilla.org')

DATABASES = {
    'default': get_db_config('DATABASES_DEFAULT_URL'),
    'replica': get_db_config('DATABASES_REPLICA_URL', atomic_requests=False),
}

SERVICES_DATABASE = get_db_config('SERVICES_DATABASE_URL')

REPLICA_DATABASES = ['replica']

CACHES = {}
CACHES['default'] = env.cache('CACHES_DEFAULT')
CACHES['default']['TIMEOUT'] = 500
CACHES['default']['BACKEND'] = CACHE_BACKEND
CACHES['default']['KEY_PREFIX'] = CACHE_KEY_PREFIX

# Celery
CELERY_BROKER_CONNECTION_TIMEOUT = 0.5

ES_TIMEOUT = 60
ES_HOSTS = env('ES_HOSTS')
ES_URLS = ['http://%s' % h for h in ES_HOSTS]
ES_INDEXES = {k: f'{v}_{ENV}' for k, v in ES_INDEXES.items()}

CEF_PRODUCT = STATSD_PREFIX

NEW_FEATURES = True

ADDONS_LINTER_BIN = 'node_modules/.bin/addons-linter'

FXA_CONFIG = {
    'default': {
        'client_id': env('FXA_CLIENT_ID'),
        'client_secret': env('FXA_CLIENT_SECRET'),
        # fxa redirects to https://%s/api/auth/authenticate-callback/ % DOMAIN
    },
}
DEFAULT_FXA_CONFIG_NAME = 'default'
ALLOWED_FXA_CONFIGS = ['default']

ES_DEFAULT_NUM_SHARDS = 10

RECOMMENDATION_ENGINE_URL = env(
    'RECOMMENDATION_ENGINE_URL',
    default='https://taar.prod.mozaws.net/v1/api/recommendations/',
)

TAAR_LITE_RECOMMENDATION_ENGINE_URL = env(
    'TAAR_LITE_RECOMMENDATION_ENGINE_URL',
    default=('https://taarlite.prod.mozaws.net/taarlite/api/v1/addon_recommendations/'),
)

FXA_SQS_AWS_QUEUE_URL = (
    'https://sqs.us-west-2.amazonaws.com/361527076523/amo-account-change-prod'
)

EXTENSION_WORKSHOP_URL = env(
    'EXTENSION_WORKSHOP_URL', default='https://extensionworkshop.com'
)

REMOTE_SETTINGS_API_URL = 'https://firefox.settings.services.mozilla.com/v1/'
REMOTE_SETTINGS_WRITER_URL = 'https://settings-writer.prod.mozaws.net/v1/'
REMOTE_SETTINGS_WRITER_BUCKET = 'staging'

# See: https://bugzilla.mozilla.org/show_bug.cgi?id=1633746
BIGQUERY_AMO_DATASET = 'amo_prod'

# We don't want to enable the new addon submission on prod yet
DRF_API_GATES['v5'] = tuple(
    gate for gate in DRF_API_GATES['v5'] if gate != 'addon-submission-api'
)

ENABLE_FEATURE_REVIEW_ACTIVITY_REASON = False
