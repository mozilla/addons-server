import logging
import os
import environ
import datetime

from lib.settings_base import *  # noqa

environ.Env.read_env(env_file='/etc/olympia/settings.env')
env = environ.Env()

ENGAGE_ROBOTS = False

EMAIL_URL = env.email_url('EMAIL_URL')
EMAIL_HOST = EMAIL_URL['EMAIL_HOST']
EMAIL_PORT = EMAIL_URL['EMAIL_PORT']
EMAIL_BACKEND = EMAIL_URL['EMAIL_BACKEND']
EMAIL_HOST_USER = EMAIL_URL['EMAIL_HOST_USER']
EMAIL_HOST_PASSWORD = EMAIL_URL['EMAIL_HOST_PASSWORD']
EMAIL_QA_WHITELIST = env.list('EMAIL_QA_WHITELIST')

ENV = env('ENV')
DEBUG = False
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = False
SESSION_COOKIE_SECURE = True
CRONJOB_LOCK_PREFIX = DOMAIN
ADMINS = ()

API_THROTTLE = False

REDIRECT_SECRET_KEY = env('REDIRECT_SECRET_KEY')

DOMAIN = env('DOMAIN', default='addons.allizom.org')
SERVER_EMAIL = 'zstage@addons.mozilla.org'
SITE_URL = 'https://' + DOMAIN
SERVICES_URL = SITE_URL
STATIC_URL = 'https://addons-stage-cdn.allizom.org/static/'
MEDIA_URL = 'https://addons-stage-cdn.allizom.org/user-media/'

CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (STATIC_URL[:-1],)
CSP_FRAME_SRC = ("'self'", "https://sandbox.paypal.com",)

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

SYSLOG_TAG = "http_app_addons_stage"
SYSLOG_TAG2 = "http_app_addons_stage_timer"
SYSLOG_CSP = "http_app_addons_stage_csp"

DATABASES = {}
DATABASES['default'] = env.db('DATABASES_DEFAULT_URL')
DATABASES['default']['ENGINE'] = 'mysql_pool'

DATABASES['slave'] = env.db('DATABASES_SLAVE_URL')
DATABASES['slave']['ENGINE'] = 'mysql_pool'
DATABASES['slave']['sa_pool_key'] = 'slave'

DATABASE_POOL_ARGS = {
    'max_overflow': 10,
    'pool_size': 5,
    'recycle': 30
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

LOG_LEVEL = logging.DEBUG

# Celery
BROKER_URL = env('BROKER_URL')

CELERY_IGNORE_RESULT = True
CELERY_DISABLE_RATE_LIMITS = True
CELERYD_PREFETCH_MULTIPLIER = 1

NETAPP_STORAGE_ROOT = env('NETAPP_STORAGE_ROOT')
NETAPP_STORAGE = NETAPP_STORAGE_ROOT + '/shared_storage'
GUARDED_ADDONS_PATH = NETAPP_STORAGE_ROOT + '/guarded-addons'
MEDIA_ROOT = NETAPP_STORAGE + '/uploads'

# Must be forced in settings because name => path can't be dyncamically
# computed: reviewer_attachmentS VS reviewer_attachment.
# TODO: rename folder on file system.
# (One can also just rename the setting, but this will not be consistent
# with the naming scheme.)
REVIEWER_ATTACHMENTS_PATH = MEDIA_ROOT + '/reviewer_attachment'

HERA = []
LOGGING['loggers'].update({
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

TMP_PATH = os.path.join(NETAPP_STORAGE, 'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')

ADDONS_PATH = NETAPP_STORAGE_ROOT + '/files'

PERF_THRESHOLD = 20

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

REDIRECT_URL = 'https://outgoing.allizom.org/v1/'

CLEANCSS_BIN = 'cleancss'
UGLIFY_BIN = 'uglifyjs'

LESS_PREPROCESS = True

XSENDFILE_HEADER = 'X-Accel-Redirect'

ALLOW_SELF_REVIEWS = True

GOOGLE_ANALYTICS_CREDENTIALS = env.dict('GOOGLE_ANALYTICS_CREDENTIALS')
GOOGLE_ANALYTICS_CREDENTIALS['user_agent'] = None
GOOGLE_ANALYTICS_CREDENTIALS['token_expiry'] = datetime.datetime(2013, 1, 3, 1, 20, 16, 45465)  # noqa

GOOGLE_API_CREDENTIALS = env('GOOGLE_API_CREDENTIALS')

GEOIP_URL = 'https://geo.services.mozilla.com'

AES_KEYS = env.dict('AES_KEYS')

PERSONA_DEFAULT_PAGES = 5

# Signing
SIGNING_SERVER = env('SIGNING_SERVER')
PRELIMINARY_SIGNING_SERVER = env('PRELIMINARY_SIGNING_SERVER')

# sandbox
PAYPAL_PAY_URL = 'https://svcs.sandbox.paypal.com/AdaptivePayments/'
PAYPAL_FLOW_URL = (
    'https://www.sandbox.paypal.com/webapps/adaptivepayment/flow/pay')
PAYPAL_API_URL = 'https://api-3t.sandbox.paypal.com/nvp'
PAYPAL_EMAIL = env('PAYPAL_EMAIL')
PAYPAL_APP_ID = env('PAYPAL_APP_ID')
PAYPAL_PERMISSIONS_URL = 'https://svcs.sandbox.paypal.com/Permissions/'
PAYPAL_CGI_URL = 'https://www.sandbox.paypal.com/cgi-bin/webscr'

PAYPAL_EMBEDDED_AUTH = {
    'USER': env('PAYPAL_EMBEDDED_AUTH_USER'),
    'PASSWORD': env('PAYPAL_EMBEDDED_AUTH_PASSWORD'),
    'SIGNATURE': env('PAYPAL_EMBEDDED_AUTH_SIGNATURE'),
}
PAYPAL_CGI_AUTH = {
    'USER': env('PAYPAL_CGI_AUTH_USER'),
    'PASSWORD': env('PAYPAL_CGI_AUTH_PASSWORD'),
    'SIGNATURE': env('PAYPAL_CGI_AUTH_SIGNATURE'),
}

PAYPAL_CHAINS = (
    (30, env('PAYPAL_CHAINS_EMAIL')),
)

SENTRY_DSN = env('SENTRY_DSN')

AMO_LANGUAGES = AMO_LANGUAGES + ('dbg',)
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])

GOOGLE_ANALYTICS_DOMAIN = 'addons.mozilla.org'

NEWRELIC_ENABLE = False

if NEWRELIC_ENABLE:
    NEWRELIC_INI = '/etc/newrelic.d/%s.ini' % DOMAIN

READ_ONLY = env.bool('READ_ONLY', default=False)
