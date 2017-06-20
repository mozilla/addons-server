import logging
import os
import environ
import datetime

from olympia.lib.settings_base import *  # noqa

environ.Env.read_env(env_file='/etc/olympia/settings.env')
env = environ.Env()

ENGAGE_ROBOTS = True

EMAIL_URL = env.email_url('EMAIL_URL')
EMAIL_HOST = EMAIL_URL['EMAIL_HOST']
EMAIL_PORT = EMAIL_URL['EMAIL_PORT']
EMAIL_BACKEND = EMAIL_URL['EMAIL_BACKEND']
EMAIL_HOST_USER = EMAIL_URL['EMAIL_HOST_USER']
EMAIL_HOST_PASSWORD = EMAIL_URL['EMAIL_HOST_PASSWORD']
EMAIL_QA_ALLOW_LIST = env.list('EMAIL_QA_ALLOW_LIST')
EMAIL_DENY_LIST = env.list('EMAIL_DENY_LIST')

SEND_REAL_EMAIL = True

ENV = env('ENV')
DEBUG = False
DEBUG_PROPAGATE_EXCEPTIONS = False
SESSION_COOKIE_SECURE = True

API_THROTTLE = False

REDIRECT_SECRET_KEY = env('REDIRECT_SECRET_KEY')

CDN_HOST = 'https://addons.cdn.mozilla.net'
DOMAIN = env('DOMAIN', default='addons.mozilla.org')
SERVER_EMAIL = 'zprod@addons.mozilla.org'
SITE_URL = 'https://' + DOMAIN
SERVICES_URL = env('SERVICES_URL',
                   default='https://services.addons.mozilla.org')
STATIC_URL = '%s/static/' % CDN_HOST
MEDIA_URL = '%s/user-media/' % CDN_HOST

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

# Filter IP addresses of allowed clients that can post email through the API.
ALLOWED_CLIENTS_EMAIL_API = env.list('ALLOWED_CLIENTS_EMAIL_API', default=[])
# Auth token required to authorize inbound email.
INBOUND_EMAIL_SECRET_KEY = env('INBOUND_EMAIL_SECRET_KEY', default='')
# Validation key we need to send in POST response.
INBOUND_EMAIL_VALIDATION_KEY = env('INBOUND_EMAIL_VALIDATION_KEY', default='')
# Domain emails should be sent to.
INBOUND_EMAIL_DOMAIN = env('INBOUND_EMAIL_DOMAIN', default=DOMAIN)

SYSLOG_TAG = "http_app_addons"
SYSLOG_TAG2 = "http_app_addons_timer"
SYSLOG_CSP = "http_app_addons_csp"

DATABASES = {}
DATABASES['default'] = env.db('DATABASES_DEFAULT_URL')
DATABASES['default']['ENGINE'] = 'django.db.backends.mysql'
# Run all views in a transaction (on master) unless they are decorated not to.
DATABASES['default']['ATOMIC_REQUESTS'] = True
# Pool our database connections up for 300 seconds
DATABASES['default']['CONN_MAX_AGE'] = 300

DATABASES['slave'] = env.db('DATABASES_SLAVE_URL')
# Do not open a transaction for every view on the slave DB.
DATABASES['slave']['ATOMIC_REQUESTS'] = False
DATABASES['slave']['ENGINE'] = 'django.db.backends.mysql'
# Pool our database connections up for 300 seconds
DATABASES['slave']['CONN_MAX_AGE'] = 300

SERVICES_DATABASE = env.db('SERVICES_DATABASE_URL')

SLAVE_DATABASES = ['slave']

CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX

CACHES = {}
CACHES['default'] = env.cache('CACHES_DEFAULT')
CACHES['default']['TIMEOUT'] = 500
CACHES['default']['BACKEND'] = 'caching.backends.memcached.MemcachedCache'
CACHES['default']['KEY_PREFIX'] = CACHE_PREFIX

SECRET_KEY = env('SECRET_KEY')


# Celery
BROKER_URL = env('BROKER_URL')

CELERY_IGNORE_RESULT = True
CELERY_DISABLE_RATE_LIMITS = True
BROKER_CONNECTION_TIMEOUT = 0.5
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND')

NETAPP_STORAGE_ROOT = env('NETAPP_STORAGE_ROOT')
NETAPP_STORAGE = NETAPP_STORAGE_ROOT + '/shared_storage'
GUARDED_ADDONS_PATH = NETAPP_STORAGE_ROOT + '/guarded-addons'
MEDIA_ROOT = NETAPP_STORAGE + '/uploads'

TMP_PATH = os.path.join(NETAPP_STORAGE, 'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')

ADDONS_PATH = NETAPP_STORAGE_ROOT + '/files'

# Must be forced in settings because name => path can't be dyncamically
# computed: reviewer_attachmentS VS reviewer_attachment.
# TODO: rename folder on file system.
# (One can also just rename the setting, but this will not be consistent
# with the naming scheme.)
REVIEWER_ATTACHMENTS_PATH = MEDIA_ROOT + '/reviewer_attachment'

LOG_LEVEL = logging.DEBUG

LOGGING['loggers'].update({
    'adi.updatecountsfromfile': {'level': logging.INFO},
    'amqp': {'level': logging.WARNING},
    'raven': {'level': logging.WARNING},
    'requests': {'level': logging.WARNING},
    'z.addons': {'level': logging.INFO},
    'z.task': {'level': logging.DEBUG},
    'z.redis': {'level': logging.DEBUG},
    'z.pool': {'level': logging.ERROR},
})

# This is used for `django-cache-machine`
REDIS_BACKEND = env('REDIS_BACKENDS_CACHE')

REDIS_BACKENDS = {
    'cache': get_redis_settings(env('REDIS_BACKENDS_CACHE')),
    'cache_slave': get_redis_settings(env('REDIS_BACKENDS_CACHE_SLAVE')),
    'master': get_redis_settings(env('REDIS_BACKENDS_MASTER')),
    'slave': get_redis_settings(env('REDIS_BACKENDS_SLAVE'))
}

CACHE_MACHINE_USE_REDIS = True

# Old recaptcha V1
RECAPTCHA_PUBLIC_KEY = env('RECAPTCHA_PUBLIC_KEY')
RECAPTCHA_PRIVATE_KEY = env('RECAPTCHA_PRIVATE_KEY')
# New Recaptcha V2
NOBOT_RECAPTCHA_PUBLIC_KEY = env('NOBOT_RECAPTCHA_PUBLIC_KEY')
NOBOT_RECAPTCHA_PRIVATE_KEY = env('NOBOT_RECAPTCHA_PRIVATE_KEY')

RESPONSYS_ID = env('RESPONSYS_ID')

ES_TIMEOUT = 60
ES_HOSTS = env('ES_HOSTS')
ES_URLS = ['http://%s' % h for h in ES_HOSTS]
ES_INDEXES = dict((k, '%s_%s' % (v, ENV)) for k, v in ES_INDEXES.items())

STATSD_HOST = env('STATSD_HOST')
STATSD_PREFIX = env('STATSD_PREFIX')

GRAPHITE_HOST = env('GRAPHITE_HOST')
GRAPHITE_PREFIX = env('GRAPHITE_PREFIX')

CEF_PRODUCT = STATSD_PREFIX

NEW_FEATURES = True

CLEANCSS_BIN = 'cleancss'
UGLIFY_BIN = 'uglifyjs'
ADDONS_LINTER_BIN = 'addons-linter'

LESS_PREPROCESS = True

XSENDFILE_HEADER = 'X-Accel-Redirect'

GOOGLE_ANALYTICS_CREDENTIALS = env.dict('GOOGLE_ANALYTICS_CREDENTIALS')
GOOGLE_ANALYTICS_CREDENTIALS['user_agent'] = None
GOOGLE_ANALYTICS_CREDENTIALS['token_expiry'] = datetime.datetime(2013, 1, 3, 1, 20, 16, 45465)  # noqa

GEOIP_URL = 'https://geo.services.mozilla.com'

AES_KEYS = env.dict('AES_KEYS')

# Signing
SIGNING_SERVER = env('SIGNING_SERVER')

PAYPAL_APP_ID = env('PAYPAL_APP_ID')

PAYPAL_EMBEDDED_AUTH = {
    'USER': env('PAYPAL_EMBEDDED_AUTH_USER'),
    'PASSWORD': env('PAYPAL_EMBEDDED_AUTH_PASSWORD'),
    'SIGNATURE': env('PAYPAL_EMBEDDED_AUTH_SIGNATURE'),
}
PAYPAL_CGI_AUTH = PAYPAL_EMBEDDED_AUTH

SENTRY_DSN = env('SENTRY_DSN')

GOOGLE_ANALYTICS_DOMAIN = 'addons.mozilla.org'

NEWRELIC_ENABLE = env.bool('NEWRELIC_ENABLE', default=False)

if NEWRELIC_ENABLE:
    NEWRELIC_INI = '/etc/newrelic.d/%s.ini' % DOMAIN

FXA_CONFIG = {
    'default': {
        'client_id': env('FXA_CLIENT_ID'),
        'client_secret': env('FXA_CLIENT_SECRET'),
        'content_host': 'https://accounts.firefox.com',
        'oauth_host': 'https://oauth.accounts.firefox.com/v1',
        'profile_host': 'https://profile.accounts.firefox.com/v1',
        'redirect_url':
            'https://%s/api/v3/accounts/authenticate/' % DOMAIN,
        'scope': 'profile',
    },
    'internal': {
        'client_id': env('INTERNAL_FXA_CLIENT_ID'),
        'client_secret': env('INTERNAL_FXA_CLIENT_SECRET'),
        'content_host': 'https://accounts.firefox.com',
        'oauth_host': 'https://oauth.accounts.firefox.com/v1',
        'profile_host': 'https://profile.accounts.firefox.com/v1',
        'redirect_url':
            'https://addons-admin.prod.mozaws.net/fxa-authenticate',
        'scope': 'profile',
    },
    'amo': {
        'client_id': env('AMO_FXA_CLIENT_ID'),
        'client_secret': env('AMO_FXA_CLIENT_SECRET'),
        'content_host': 'https://accounts.firefox.com',
        'oauth_host': 'https://oauth.accounts.firefox.com/v1',
        'profile_host': 'https://profile.accounts.firefox.com/v1',
        'redirect_url':
            'https://addons.mozilla.org/api/v3/accounts/authenticate/',
        'scope': 'profile',
        'skip_register_redirect': True,
    },
}
DEFAULT_FXA_CONFIG_NAME = 'default'
INTERNAL_FXA_CONFIG_NAME = 'internal'
ALLOWED_FXA_CONFIGS = ['default', 'amo']

CORS_ENDPOINT_OVERRIDES = cors_endpoint_overrides(
    public=['amo.addons.mozilla.org'],
    internal=['addons-admin.prod.mozaws.net'],
)

VALIDATOR_TIMEOUT = 360

ES_DEFAULT_NUM_SHARDS = 10

READ_ONLY = env.bool('READ_ONLY', default=False)

RAVEN_DSN = (
    'https://8c1c5936578948a9a0614cbbafccf049@sentry.prod.mozaws.net/78')
RAVEN_ALLOW_LIST = ['addons.mozilla.org', 'addons.cdn.mozilla.net']

GITHUB_API_USER = env('GITHUB_API_USER')
GITHUB_API_TOKEN = env('GITHUB_API_TOKEN')
