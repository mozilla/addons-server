"""private_base will be populated from puppet and placed in this directory"""

import logging
import os

import dj_database_url

from lib.settings_base import (CACHE_PREFIX, ES_INDEXES,
                               KNOWN_PROXIES, LOGGING, HOSTNAME)

from .. import splitstrip
import private_base as private


ENGAGE_ROBOTS = False

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = private.EMAIL_HOST

DEBUG = False
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = False
SESSION_COOKIE_SECURE = True
REDIRECT_SECRET_KEY = private.REDIRECT_SECRET_KEY

ADMINS = ()

DATABASES = {}
DATABASES['default'] = dj_database_url.parse(private.DATABASES_DEFAULT_URL)
DATABASES['default']['ENGINE'] = 'mysql_pool'
DATABASES['default']['OPTIONS'] = {'init_command': 'SET storage_engine=InnoDB'}

DATABASES['slave'] = dj_database_url.parse(private.DATABASES_SLAVE_URL)
DATABASES['slave']['ENGINE'] = 'mysql_pool'
DATABASES['slave']['OPTIONS'] = {'init_command': 'SET storage_engine=InnoDB'}
DATABASES['slave']['sa_pool_key'] = 'slave'

DATABASE_POOL_ARGS = {
    'max_overflow': 10,
    'pool_size': 5,
    'recycle': 30
}

SERVICES_DATABASE = dj_database_url.parse(private.SERVICES_DATABASE_URL)

SLAVE_DATABASES = ['slave']

CACHES = {
    'default': {
        'BACKEND': 'caching.backends.memcached.MemcachedCache',
        'LOCATION': splitstrip(private.CACHES_DEFAULT_LOCATION),
        'TIMEOUT': 500,
        'KEY_PREFIX': CACHE_PREFIX,
    }
}

SECRET_KEY = private.SECRET_KEY

LOG_LEVEL = logging.DEBUG

## Celery
BROKER_URL = private.BROKER_URL

CELERY_IGNORE_RESULT = True
CELERY_DISABLE_RATE_LIMITS = True
CELERYD_PREFETCH_MULTIPLIER = 1

NETAPP_STORAGE = private.NETAPP_STORAGE_ROOT + '/shared_storage'
GUARDED_ADDONS_PATH = private.NETAPP_STORAGE_ROOT + '/guarded-addons'
MEDIA_ROOT = NETAPP_STORAGE + '/uploads'

# Must be forced in settings because name => path can't be dyncamically
# computed: reviewer_attachmentS VS reviewer_attachment.
# TODO: rename folder on file system.
# (One can also just rename the setting, but this will not be consistent
# with the naming scheme.)
REVIEWER_ATTACHMENTS_PATH = MEDIA_ROOT + '/reviewer_attachment'

HERA = []
LOGGING['loggers'].update({
    'amqp': {'level': logging.WARNING},
    'raven': {'level': logging.WARNING},
    'requests': {'level': logging.WARNING},
    'z.addons': {'level': logging.DEBUG},
    'z.task': {'level': logging.DEBUG},
    'z.hera': {'level': logging.INFO},
    'z.redis': {'level': logging.DEBUG},
    'z.pool': {'level': logging.ERROR},
})

REDIS_BACKEND = private.REDIS_BACKENDS_CACHE
REDIS_BACKENDS = {
    'cache': private.REDIS_BACKENDS_CACHE,
    'cache_slave': private.REDIS_BACKENDS_CACHE_SLAVE,
    'master': private.REDIS_BACKENDS_MASTER,
    'slave': private.REDIS_BACKENDS_SLAVE,
}
CACHE_MACHINE_USE_REDIS = True

RECAPTCHA_PUBLIC_KEY = private.RECAPTCHA_PUBLIC_KEY
RECAPTCHA_PRIVATE_KEY = private.RECAPTCHA_PRIVATE_KEY
RECAPTCHA_URL = ('https://www.google.com/recaptcha/api/challenge?k=%s' %
                 RECAPTCHA_PUBLIC_KEY)

TMP_PATH = os.path.join(NETAPP_STORAGE, 'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')

ADDONS_PATH = private.NETAPP_STORAGE_ROOT + '/files'

PERF_THRESHOLD = 20

SPIDERMONKEY = '/usr/bin/tracemonkey'

# Remove DetectMobileMiddleware from middleware in production.
detect = 'mobility.middleware.DetectMobileMiddleware'
csp = 'csp.middleware.CSPMiddleware'


RESPONSYS_ID = private.RESPONSYS_ID

CRONJOB_LOCK_PREFIX = 'addons-dev'

BUILDER_SECRET_KEY = private.BUILDER_SECRET_KEY
BUILDER_VERSIONS_URL = "https://builder-addons-dev.allizom.org/repackage/sdk-versions/"


ES_HOSTS = splitstrip(private.ES_HOSTS)
ES_URLS = ['http://%s' % h for h in ES_HOSTS]
ES_INDEXES = dict((k, '%s_dev' % v) for k, v in ES_INDEXES.items())

BUILDER_UPGRADE_URL = "https://builder-addons-dev.allizom.org/repackage/rebuild/"

STATSD_HOST = private.STATSD_HOST
STATSD_PORT = private.STATSD_PORT
STATSD_PREFIX = private.STATSD_PREFIX

GRAPHITE_HOST = private.GRAPHITE_HOST
GRAPHITE_PORT = private.GRAPHITE_PORT
GRAPHITE_PREFIX = private.GRAPHITE_PREFIX

CEF_PRODUCT = STATSD_PREFIX

ES_TIMEOUT = 60

EXPOSE_VALIDATOR_TRACEBACKS = True

KNOWN_PROXIES += ['10.2.83.105',
                  '10.2.83.106',
                  '10.2.83.107',
                  '10.8.83.200',
                  '10.8.83.201',
                  '10.8.83.202',
                  '10.8.83.203',
                  '10.8.83.204',
                  '10.8.83.210',
                  '10.8.83.211',
                  '10.8.83.212',
                  '10.8.83.213',
                  '10.8.83.214',
                  '10.8.83.215',
                  '10.8.83.251',
                  '10.8.83.252',
                  '10.8.83.253',
                  ]

NEW_FEATURES = True

PERF_TEST_URL = 'http://talos-addon-master1.amotest.scl1.mozilla.com/trigger/trigger.cgi'

REDIRECT_URL = 'https://outgoing-mkt-dev.allizom.org/v1/'

CLEANCSS_BIN = 'cleancss'
UGLIFY_BIN = 'uglifyjs'

LESS_PREPROCESS = True

XSENDFILE_HEADER = 'X-Accel-Redirect'

ALLOW_SELF_REVIEWS = True

GOOGLE_ANALYTICS_CREDENTIALS = private.GOOGLE_ANALYTICS_CREDENTIALS
GOOGLE_API_CREDENTIALS = private.GOOGLE_API_CREDENTIALS

GEOIP_URL = 'https://geo-dev-marketplace.allizom.org'

AWS_ACCESS_KEY_ID = private.AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY = private.AWS_SECRET_ACCESS_KEY
AWS_STORAGE_BUCKET_NAME = private.AWS_STORAGE_BUCKET_NAME

RAISE_ON_SIGNAL_ERROR = True

API_THROTTLE = False

NEWRELIC_WHITELIST = ['dev1.addons.phx1.mozilla.com',
                      'dev2.addons.phx1.mozilla.com']

NEWRELIC_ENABLE = HOSTNAME in NEWRELIC_WHITELIST

AES_KEYS = private.AES_KEYS

PERSONA_DEFAULT_PAGES = 2
