"""private_base will be populated from puppet and placed in this directory"""

import logging
import os

import dj_database_url

from lib.settings_base import CACHE_PREFIX, KNOWN_PROXIES, LOGGING

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

SPHINX_HOST = private.SPHINX_HOST
SPHINX_PORT = private.SPHINX_PORT

CACHES = {
    'default': {
        'BACKEND': 'caching.backends.memcached.CacheClass',
        'LOCATION': splitstrip(private.CACHES_DEFAULT_LOCATION),
        'TIMEOUT': 500,
        'KEY_PREFIX': CACHE_PREFIX,
    },
}

SECRET_KEY = private.SECRET_KEY

LOG_LEVEL = logging.DEBUG

## Celery
BROKER_URL = private.BROKER_URL
CELERY_IGNORE_RESULT = True
CELERY_DISABLE_RATE_LIMITS = True
CELERYD_PREFETCH_MULTIPLIER = 1

NETAPP_STORAGE = private.NETAPP_STORAGE_ROOT + '/shared_storage'
MIRROR_STAGE_PATH = private.NETAPP_STORAGE_ROOT + '/public-staging'
GUARDED_ADDONS_PATH = private.NETAPP_STORAGE_ROOT + '/guarded-addons'
WATERMARKED_ADDONS_PATH = private.NETAPP_STORAGE_ROOT + '/watermarked-addons'
UPLOADS_PATH = NETAPP_STORAGE + '/uploads'
USERPICS_PATH = UPLOADS_PATH + '/userpics'
ADDON_ICONS_PATH = UPLOADS_PATH + '/addon_icons'
COLLECTIONS_ICON_PATH = UPLOADS_PATH + '/collection_icons'
IMAGEASSETS_PATH = UPLOADS_PATH + '/imageassets'
IMAGEASSET_FULL_PATH = IMAGEASSETS_PATH + '/%s/%d.%s'
PERSONAS_PATH = UPLOADS_PATH + '/themes'
PREVIEWS_PATH = UPLOADS_PATH + '/previews'
SIGNED_APPS_PATH = NETAPP_STORAGE + '/signed_apps'
SIGNED_APPS_REVIEWER_PATH = NETAPP_STORAGE + '/signed_apps_reviewer'
PREVIEW_THUMBNAIL_PATH = PREVIEWS_PATH + '/thumbs/%s/%d.png'
PREVIEW_FULL_PATH = PREVIEWS_PATH + '/full/%s/%d.%s'

HERA = []
LOGGING['loggers'].update({
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
RECAPTCHA_URL = ('https://www.google.com/recaptcha/api/challenge?k=%s' % RECAPTCHA_PUBLIC_KEY)

TMP_PATH = os.path.join(NETAPP_STORAGE, 'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')

ADDONS_PATH = private.NETAPP_STORAGE_ROOT + '/files'

SPHINX_CATALOG_PATH = TMP_PATH + '/data/sphinx'
SPHINX_LOG_PATH = TMP_PATH + '/log/searchd'

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
ES_INDEXES = {'default': 'addons_dev',
              'update_counts': 'addons_dev_stats',
              'download_counts': 'addons_dev_stats'}

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

REDIRECT_URL = 'https://outgoing.allizom.org/v1/'

CLEANCSS_BIN = 'cleancss'
UGLIFY_BIN = 'uglifyjs'

CELERYD_TASK_SOFT_TIME_LIMIT = 240

LESS_PREPROCESS = True

XSENDFILE_HEADER = 'X-Accel-Redirect'

GEOIP_NOOP = 0

ALLOW_SELF_REVIEWS = True

GOOGLE_ANALYTICS_CREDENTIALS = private.GOOGLE_ANALYTICS_CREDENTIALS
