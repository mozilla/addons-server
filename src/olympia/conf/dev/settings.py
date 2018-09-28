import logging
import os

from olympia.lib.settings_base import *  # noqa


# Allow addons-dev CDN for CSP.
CSP_BASE_URI += (
    # Required for the legacy discovery pane.
    'https://addons-dev.allizom.org',
)
CDN_HOST = 'https://addons-dev-cdn.allizom.org'
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

API_THROTTLE = False

DOMAIN = env('DOMAIN', default='addons-dev.allizom.org')
SERVER_EMAIL = 'zdev@addons.mozilla.org'
SITE_URL = 'https://' + DOMAIN
SERVICES_URL = env('SERVICES_URL',
                   default='https://services.addons-dev.allizom.org')
STATIC_URL = '%s/static/' % CDN_HOST
MEDIA_URL = '%s/user-media/' % CDN_HOST

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

# Domain emails should be sent to.
INBOUND_EMAIL_DOMAIN = env('INBOUND_EMAIL_DOMAIN',
                           default='addons-dev.allizom.org')

NETAPP_STORAGE_ROOT = env('NETAPP_STORAGE_ROOT')
NETAPP_STORAGE = NETAPP_STORAGE_ROOT + '/shared_storage'
GUARDED_ADDONS_PATH = NETAPP_STORAGE_ROOT + '/guarded-addons'
MEDIA_ROOT = NETAPP_STORAGE + '/uploads'
TMP_PATH = os.path.join(NETAPP_STORAGE, 'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')

ADDONS_PATH = NETAPP_STORAGE_ROOT + '/files'

REVIEWER_ATTACHMENTS_PATH = MEDIA_ROOT + '/reviewer_attachment'

DATABASES = {
    'default': get_db_config('DATABASES_DEFAULT_URL'),
    'slave': get_db_config('DATABASES_SLAVE_URL'),
}

SERVICES_DATABASE = get_db_config('SERVICES_DATABASE_URL')

SLAVE_DATABASES = ['slave']

CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX

CACHES = {}
CACHES['default'] = env.cache('CACHES_DEFAULT')
CACHES['default']['TIMEOUT'] = 500
CACHES['default']['BACKEND'] = 'django.core.cache.backends.memcached.MemcachedCache'  # noqa
CACHES['default']['KEY_PREFIX'] = CACHE_PREFIX

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

XSENDFILE_HEADER = 'X-Accel-Redirect'

ALLOW_SELF_REVIEWS = True

PERSONA_DEFAULT_PAGES = 2

AMO_LANGUAGES = AMO_LANGUAGES + DEBUG_LANGUAGES
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])

NEWRELIC_ENABLE = env.bool('NEWRELIC_ENABLE', default=False)

if NEWRELIC_ENABLE:
    NEWRELIC_INI = '/etc/newrelic.d/%s.ini' % DOMAIN

FXA_CONFIG = {
    'default': {
        'client_id': env('FXA_CLIENT_ID'),
        'client_secret': env('FXA_CLIENT_SECRET'),
        'content_host': 'https://stable.dev.lcip.org',
        'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
        'profile_host': 'https://stable.dev.lcip.org/profile/v1',
        'redirect_url':
            'https://%s/api/v3/accounts/authenticate/' % DOMAIN,
        'scope': 'profile',
    },
    'amo': {
        'client_id': env('AMO_FXA_CLIENT_ID'),
        'client_secret': env('AMO_FXA_CLIENT_SECRET'),
        'content_host': 'https://stable.dev.lcip.org',
        'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
        'profile_host': 'https://stable.dev.lcip.org/profile/v1',
        'redirect_url': 'https://amo.addons-dev.allizom.org/fxa-authenticate',
        'scope': 'profile',
    },
    'local': {
        'client_id': env('DEVELOPMENT_FXA_CLIENT_ID'),
        'client_secret': env('DEVELOPMENT_FXA_CLIENT_SECRET'),
        'content_host': 'https://stable.dev.lcip.org',
        'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
        'profile_host': 'https://stable.dev.lcip.org/profile/v1',
        'redirect_url': 'http://localhost:3000/fxa-authenticate',
        'scope': 'profile',
    },
}
DEFAULT_FXA_CONFIG_NAME = 'default'
ALLOWED_FXA_CONFIGS = ['default', 'amo', 'local']

CORS_ENDPOINT_OVERRIDES = cors_endpoint_overrides(
    ['amo.addons-dev.allizom.org', 'localhost:3000']
)

RAVEN_JS_DSN = (
    'https://5686e2a8f14446a3940c651c6a14dc73@sentry.prod.mozaws.net/75')
RAVEN_JS_ALLOW_LIST = ['addons-dev.allizom.org', 'addons-dev-cdn.allizom.org']

FXA_SQS_AWS_QUEUE_URL = (
    'https://sqs.us-east-1.amazonaws.com/927034868273/'
    'amo-account-change-dev')

VAMO_URL = 'https://versioncheck-dev.allizom.org'
