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
SERVER_EMAIL = 'zstage@addons.mozilla.org'
SITE_URL = 'https://' + DOMAIN
INTERNAL_SITE_URL = env('INTERNAL_SITE_URL', default='https://addons.allizom.org')
EXTERNAL_SITE_URL = env('EXTERNAL_SITE_URL', default='https://addons.allizom.org')
SERVICES_URL = env('SERVICES_URL', default='https://services.addons.allizom.org')
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

SERVICES_DATABASE = get_db_config('SERVICES_DATABASE_URL')

REPLICA_DATABASES = ['replica']

# Celery
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# Update the logger name used for mozlog
LOGGING['formatters']['json']['logger_name'] = 'http_app_addons_stage'

csp = 'csp.middleware.CSPMiddleware'

ES_TIMEOUT = 60
ES_HOSTS = env('ES_HOSTS')
ES_URLS = ['http://%s' % h for h in ES_HOSTS]
ES_INDEXES = {k: f'{v}_{ENV}' for k, v in ES_INDEXES.items()}

CEF_PRODUCT = STATSD_PREFIX

NEW_FEATURES = True

REDIRECT_URL = 'https://outgoing.stage.mozaws.net/v1/'

ADDONS_LINTER_BIN = 'node_modules/.bin/addons-linter'

ALLOW_SELF_REVIEWS = True

FXA_CONFIG = {
    'default': {
        'client_id': env('FXA_CLIENT_ID'),
        'client_secret': env('FXA_CLIENT_SECRET'),
        # fxa redirects to https://%s/api/auth/authenticate-callback/ % DOMAIN
    },
    'local': {
        'client_id': env('DEVELOPMENT_FXA_CLIENT_ID'),
        'client_secret': env('DEVELOPMENT_FXA_CLIENT_SECRET'),
        # fxa redirects to http://localhost:3000/api/auth/authenticate-callback/?config=local  # noqa
    },
}
DEFAULT_FXA_CONFIG_NAME = 'default'
ALLOWED_FXA_CONFIGS = ['default', 'local']

TAAR_LITE_RECOMMENDATION_ENGINE_URL = env(
    'TAAR_LITE_RECOMMENDATION_ENGINE_URL',
    default=('https://taarlite.prod.mozaws.net/taarlite/api/v1/addon_recommendations/'),
)

EXTENSION_WORKSHOP_URL = env(
    'EXTENSION_WORKSHOP_URL', default='https://extensionworkshop.allizom.org'
)

REMOTE_SETTINGS_API_URL = 'https://settings-cdn.stage.mozaws.net/v1/'
REMOTE_SETTINGS_WRITER_URL = 'https://settings-writer.stage.mozaws.net/v1/'
REMOTE_SETTINGS_WRITER_BUCKET = 'staging'
