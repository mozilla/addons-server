import logging
import os
import environ
import datetime

from olympia.lib.settings_base import *  # noqa

environ.Env.read_env(env_file='/etc/olympia/settings.env')
env = environ.Env()

CDN_HOST = 'https://addons-stage-cdn.allizom.org'
CSP_FONT_SRC += (CDN_HOST,)
CSP_FRAME_SRC += ('https://www.sandbox.paypal.com',)
CSP_IMG_SRC += (CDN_HOST,)
CSP_SCRIPT_SRC += (
    # Fix for discovery pane when using services subdomain.
    'https://addons.allizom.org',
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
EMAIL_QA_WHITELIST = env.list('EMAIL_QA_WHITELIST')

ENV = env('ENV')
DEBUG = False
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = False
SESSION_COOKIE_SECURE = True
CRONJOB_LOCK_PREFIX = DOMAIN

API_THROTTLE = False

REDIRECT_SECRET_KEY = env('REDIRECT_SECRET_KEY')

DOMAIN = env('DOMAIN', default='addons.allizom.org')
SERVER_EMAIL = 'zstage@addons.mozilla.org'
SITE_URL = 'https://' + DOMAIN
SERVICES_URL = env('SERVICES_URL',
                   default='https://services.addons.allizom.org')
STATIC_URL = '%s/static/' % CDN_HOST
MEDIA_URL = '%s/user-media/' % CDN_HOST

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

SYSLOG_TAG = "http_app_addons_stage"
SYSLOG_TAG2 = "http_app_addons_stage_timer"
SYSLOG_CSP = "http_app_addons_stage_csp"

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
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND')

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

LOGGING['loggers'].update({
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

REDIRECT_URL = 'https://outgoing.stage.mozaws.net/v1/'

CLEANCSS_BIN = 'cleancss'
UGLIFY_BIN = 'uglifyjs'
ADDONS_LINTER_BIN = 'addons-linter'

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
            'https://addons.allizom.org/api/v3/accounts/authorize/',
        'scope': 'profile',
    },
    'internal': {
        'client_id': env('INTERNAL_FXA_CLIENT_ID'),
        'client_secret': env('INTERNAL_FXA_CLIENT_SECRET'),
        'content_host': 'https://accounts.firefox.com',
        'oauth_host': 'https://oauth.accounts.firefox.com/v1',
        'profile_host': 'https://profile.accounts.firefox.com/v1',
        'redirect_url':
            'https://addons.allizom.org/api/v3/accounts/authorize/',
        'scope': 'profile',
    },
}

INTERNAL_DOMAINS = ['addons-admin.stage.mozaws.net']
for regex, overrides in CORS_ENDPOINT_OVERRIDES:
    overrides['CORS_ORIGIN_WHITELIST'] = INTERNAL_DOMAINS

READ_ONLY = env.bool('READ_ONLY', default=False)

RAVEN_DSN = (
    'https://e35602be5252460d97587478bcc642df@sentry.prod.mozaws.net/77')
RAVEN_WHITELIST = ['addons.allizom.org', 'addons-cdn.allizom.org']
