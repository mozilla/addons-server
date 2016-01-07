import logging
import os
import environ
import datetime

from lib.settings_base import *  # noqa

environ.Env.read_env(env_file='/etc/olympia/settings.env')
env = environ.Env()

ENGAGE_ROBOTS = True

EMAIL_URL = env.email_url('EMAIL_URL')
EMAIL_HOST = EMAIL_URL['EMAIL_HOST']
EMAIL_PORT = EMAIL_URL['EMAIL_PORT']
EMAIL_BACKEND = EMAIL_URL['EMAIL_BACKEND']
EMAIL_HOST_USER = EMAIL_URL['EMAIL_HOST_USER']
EMAIL_HOST_PASSWORD = EMAIL_URL['EMAIL_HOST_PASSWORD']
EMAIL_BLACKLIST = env.list('EMAIL_BLACKLIST')

SEND_REAL_EMAIL = True

ENV = env('ENV')
DEBUG = False
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = False
SESSION_COOKIE_SECURE = True
ADMINS = ()

API_THROTTLE = False

REDIRECT_SECRET_KEY = env('REDIRECT_SECRET_KEY')

DOMAIN = env('DOMAIN', default='addons.mozilla.org')
CRONJOB_LOCK_PREFIX = DOMAIN
SERVER_EMAIL = 'zprod@addons.mozilla.org'
SITE_URL = 'https://' + DOMAIN
SERVICES_URL = 'https://services.addons.mozilla.org'
STATIC_URL = 'https://addons.cdn.mozilla.net/static/'
MEDIA_URL = 'https://addons.cdn.mozilla.net/user-media/'
CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (STATIC_URL[:-1],)
CSP_FRAME_SRC = ("'self'", "https://*.paypal.com",)

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

SYSLOG_TAG = "http_app_addons"
SYSLOG_TAG2 = "http_app_addons_timer"
SYSLOG_CSP = "http_app_addons_csp"

DATABASES = {}
DATABASES['default'] = env.db('DATABASES_DEFAULT_URL')
DATABASES['default']['ENGINE'] = 'mysql_pool'
# Run all views in a transaction (on master) unless they are decorated not to.
DATABASES['default']['ATOMIC_REQUESTS'] = True

DATABASES['slave'] = env.db('DATABASES_SLAVE_URL')
# Do not open a transaction for every view on the slave DB.
DATABASES['slave']['ATOMIC_REQUESTS'] = False
DATABASES['slave']['ENGINE'] = 'mysql_pool'
DATABASES['slave']['sa_pool_key'] = 'slave'

DATABASE_POOL_ARGS = {
    'max_overflow': 10,
    'pool_size': 5,
    'recycle': 300
}

SERVICES_DATABASE = env.db('SERVICES_DATABASE_URL')

SLAVE_DATABASES = ['slave']

CACHE_PREFIX = 'olympia.%s' % ENV
KEY_PREFIX = CACHE_PREFIX
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

NETAPP_STORAGE_ROOT = env(u'NETAPP_STORAGE_ROOT')
NETAPP_STORAGE = NETAPP_STORAGE_ROOT + u'/shared_storage'
GUARDED_ADDONS_PATH = NETAPP_STORAGE_ROOT + u'/guarded-addons'
MEDIA_ROOT = NETAPP_STORAGE + u'/uploads'

# Must be forced in settings because name => path can't be dyncamically
# computed: reviewer_attachmentS VS reviewer_attachment.
# TODO: rename folder on file system.
# (One can also just rename the setting, but this will not be consistent
# with the naming scheme.)
REVIEWER_ATTACHMENTS_PATH = MEDIA_ROOT + '/reviewer_attachment'

HERA = []

LOG_LEVEL = logging.DEBUG

LOGGING['loggers'].update({
    'adi.updatecountsfromfile': {'level': logging.INFO},
    'amqp': {'level': logging.WARNING},
    'raven': {'level': logging.WARNING},
    'requests': {'level': logging.WARNING},
    'z.addons': {'level': logging.INFO},
    'z.task': {'level': logging.DEBUG},
    'z.hera': {'level': logging.INFO},
    'z.redis': {'level': logging.DEBUG},
    'z.pool': {'level': logging.ERROR},
})

REDIS_BACKEND = env('REDIS_BACKENDS_CACHE')
REDIS_BACKENDS = {
    'cache': env('REDIS_BACKENDS_CACHE'),
    'cache_slave': env('REDIS_BACKENDS_CACHE_SLAVE'),
    'master': env('REDIS_BACKENDS_MASTER'),
    'slave': env('REDIS_BACKENDS_SLAVE')
}

CACHE_MACHINE_USE_REDIS = True

RECAPTCHA_PUBLIC_KEY = env('RECAPTCHA_PUBLIC_KEY')
RECAPTCHA_PRIVATE_KEY = env('RECAPTCHA_PRIVATE_KEY')
RECAPTCHA_URL = ('https://www.google.com/recaptcha/api/challenge?k=%s' %
                 RECAPTCHA_PUBLIC_KEY)

TMP_PATH = os.path.join(NETAPP_STORAGE, u'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')

ADDONS_PATH = NETAPP_STORAGE_ROOT + u'/files'

SPIDERMONKEY = '/usr/bin/tracemonkey'

# Remove DetectMobileMiddleware from middleware in production.
detect = 'mobility.middleware.DetectMobileMiddleware'
csp = 'csp.middleware.CSPMiddleware'

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

LESS_PREPROCESS = True

XSENDFILE_HEADER = 'X-Accel-Redirect'

GOOGLE_ANALYTICS_CREDENTIALS = env.dict('GOOGLE_ANALYTICS_CREDENTIALS')
GOOGLE_ANALYTICS_CREDENTIALS['user_agent'] = None
GOOGLE_ANALYTICS_CREDENTIALS['token_expiry'] = datetime.datetime(2013, 1, 3, 1, 20, 16, 45465)  # noqa

GOOGLE_API_CREDENTIALS = env('GOOGLE_API_CREDENTIALS')

GEOIP_URL = 'https://geo.services.mozilla.com'

AES_KEYS = env.dict('AES_KEYS')

# Signing
SIGNING_SERVER = env('SIGNING_SERVER')
PRELIMINARY_SIGNING_SERVER = env('PRELIMINARY_SIGNING_SERVER')

PAYPAL_APP_ID = env('PAYPAL_APP_ID')

PAYPAL_EMBEDDED_AUTH = {
    'USER': env('PAYPAL_EMBEDDED_AUTH_USER'),
    'PASSWORD': env('PAYPAL_EMBEDDED_AUTH_PASSWORD'),
    'SIGNATURE': env('PAYPAL_EMBEDDED_AUTH_SIGNATURE'),
}
PAYPAL_CGI_AUTH = PAYPAL_EMBEDDED_AUTH

SENTRY_DSN = env('SENTRY_DSN')

GOOGLE_ANALYTICS_DOMAIN = 'addons.mozilla.org'

NEWRELIC_ENABLE = False

if NEWRELIC_ENABLE:
    NEWRELIC_INI = '/etc/newrelic.d/%s.ini' % DOMAIN

MIDDLEWARE_CLASSES = tuple(m for m in MIDDLEWARE_CLASSES if m not in (csp,))

VALIDATOR_TIMEOUT = 360

ES_DEFAULT_NUM_SHARDS = 10

READ_ONLY = env.bool('READ_ONLY', default=False)

restyle = 'css/restyle.less'
zamboni = tuple(list(MINIFY_BUNDLES['css']['zamboni/css']).remove(restyle))
impala = tuple(list(MINIFY_BUNDLES['css']['zamboni/impala']).remove(restyle))
devhub = tuple(list(MINIFY_BUNDLES['css']['zamboni/devhub_impala'])
               .remove(restyle))

MINIFY_BUNDLES['css']['zamboni/css'] = zamboni
MINIFY_BUNDLES['css']['zamboni/impala'] = impala
MINIFY_BUNDLES['css']['zamboni/devhub'] = devhub
