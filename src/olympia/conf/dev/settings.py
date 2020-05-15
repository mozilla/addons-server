import logging

from olympia.lib.settings_base import *  # noqa


# Allow addons-dev CDN for CSP.
CSP_BASE_URI += (
    # Required for the legacy discovery pane.
    'https://addons-dev.allizom.org',
)
CDN_HOST = 'https://addons-dev-cdn.allizom.org'
CSP_CONNECT_SRC += (CDN_HOST,)
CSP_FONT_SRC += (CDN_HOST,)
CSP_IMG_SRC += (CDN_HOST,)
CSP_SCRIPT_SRC += (
    CDN_HOST,
)
CSP_STYLE_SRC += (CDN_HOST,)

ENGAGE_ROBOTS = False

EMAIL_URL = env.email_url('EMAIL_URL')
EMAIL_HOST = EMAIL_URL['EMAIL_HOST']
EMAIL_PORT = EMAIL_URL['EMAIL_PORT']
EMAIL_BACKEND = EMAIL_URL['EMAIL_BACKEND']
EMAIL_HOST_USER = EMAIL_URL['EMAIL_HOST_USER']
EMAIL_HOST_PASSWORD = EMAIL_URL['EMAIL_HOST_PASSWORD']

ENV = env('ENV')
RAISE_ON_SIGNAL_ERROR = True

API_THROTTLING = False

DOMAIN = env('DOMAIN', default='addons-dev.allizom.org')
SERVER_EMAIL = 'zdev@addons.mozilla.org'
SITE_URL = 'https://' + DOMAIN
EXTERNAL_SITE_URL = env('EXTERNAL_SITE_URL',
                        default='https://addons-dev.allizom.org')
SERVICES_URL = env('SERVICES_URL',
                   default='https://services.addons-dev.allizom.org')
CODE_MANAGER_URL = env('CODE_MANAGER_URL',
                       default='https://code.addons-dev.allizom.org')
STATIC_URL = '%s/static/' % CDN_HOST
MEDIA_URL = '%s/user-media/' % CDN_HOST

SESSION_COOKIE_DOMAIN = '.%s' % DOMAIN

# Domain emails should be sent to.
INBOUND_EMAIL_DOMAIN = env('INBOUND_EMAIL_DOMAIN',
                           default='addons-dev.allizom.org')

DATABASES = {
    'default': get_db_config('DATABASES_DEFAULT_URL'),
    'replica': get_db_config('DATABASES_REPLICA_URL', atomic_requests=False),
}

SERVICES_DATABASE = get_db_config('SERVICES_DATABASE_URL')

REPLICA_DATABASES = ['replica']

CACHES = {}
CACHES['default'] = env.cache('CACHES_DEFAULT')
CACHES['default']['TIMEOUT'] = 500
CACHES['default']['BACKEND'] = 'django.core.cache.backends.memcached.MemcachedCache'  # noqa
CACHES['default']['KEY_PREFIX'] = CACHE_KEY_PREFIX

# Celery
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

LOGGING['loggers'].update({
    'amqp': {'level': logging.WARNING},
    'raven': {'level': logging.WARNING},
    'requests': {'level': logging.WARNING},
    'z.addons': {'level': logging.DEBUG},
    'z.task': {'level': logging.DEBUG},
    'z.pool': {'level': logging.ERROR},
})

# Update the logger name used for mozlog
LOGGING['formatters']['json']['logger_name'] = 'http_app_addons_dev'

csp = 'csp.middleware.CSPMiddleware'

ES_TIMEOUT = 60
ES_HOSTS = env('ES_HOSTS')
ES_URLS = ['http://%s' % h for h in ES_HOSTS]
ES_INDEXES = dict((k, '%s_%s' % (v, ENV)) for k, v in ES_INDEXES.items())

CEF_PRODUCT = STATSD_PREFIX

NEW_FEATURES = True

REDIRECT_URL = 'https://outgoing.stage.mozaws.net/v1/'

ADDONS_LINTER_BIN = 'node_modules/.bin/addons-linter'

ALLOW_SELF_REVIEWS = True

NEWRELIC_ENABLE = env.bool('NEWRELIC_ENABLE', default=False)

if NEWRELIC_ENABLE:
    NEWRELIC_INI = '/etc/newrelic.d/%s.ini' % DOMAIN

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
FXA_CONTENT_HOST = 'https://stable.dev.lcip.org'
FXA_OAUTH_HOST = 'https://oauth-stable.dev.lcip.org/v1'
FXA_PROFILE_HOST = 'https://stable.dev.lcip.org/profile/v1'
DEFAULT_FXA_CONFIG_NAME = 'default'
ALLOWED_FXA_CONFIGS = ['default', 'local']

FXA_SQS_AWS_QUEUE_URL = (
    'https://sqs.us-east-1.amazonaws.com/927034868273/'
    'amo-account-change-dev')

VAMO_URL = 'https://versioncheck-dev.allizom.org'

KINTO_API_IS_TEST_SERVER = True
