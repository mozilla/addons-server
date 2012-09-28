"""private_base will be populated from puppet and placed in this directory"""

import logging
import os

from lib.settings_base import CACHE_PREFIX, KNOWN_PROXIES, LOGGING, AMO_LANGUAGES, lazy, lazy_langs
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

SENTRY_DSN = private.SENTRY_DSN


DATABASES = {
    'default': {
        'NAME': private.DATABASES_DEFAULT_NAME,
        'ENGINE': 'mysql_pool',
        'HOST': private.DATABASES_DEFAULT_HOST,
        'PORT': private.DATABASES_DEFAULT_PORT,
        'USER': private.DATABASES_DEFAULT_USER,
        'PASSWORD': private.DATABASES_DEFAULT_PASSWORD,
        'OPTIONS': {'init_command': 'SET storage_engine=InnoDB'},
    },
    'slave': {
        'NAME': private.DATABASES_SLAVE_NAME,
        'ENGINE': 'mysql_pool',
        'HOST': private.DATABASES_SLAVE_HOST,
        'PORT': private.DATABASES_SLAVE_PORT,
        'USER': private.DATABASES_SLAVE_USER,
        'PASSWORD': private.DATABASES_SLAVE_PASSWORD,
        'OPTIONS': {'init_command': 'SET storage_engine=InnoDB'},
    },
}

DATABASE_POOL_ARGS = {
    'backend': 'mysql_pymysql.base',
    'max_overflow': 10,
    'pool_size':10,
    'recycle': 30
}

SERVICES_DATABASE = {
    'NAME': private.SERVICES_DATABASE_NAME,
    'USER': private.SERVICES_DATABASE_USER,
    'PASSWORD': private.SERVICES_DATABASE_PASSWORD,
    'HOST': private.SERVICES_DATABASE_HOST}

SLAVE_DATABASES = ['slave']

SPHINX_HOST = private.SPHINX_HOST
SPHINX_PORT = private.SPHINX_PORT

CACHES = {
    'default': {
#        'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
        'BACKEND': 'memcachepool.cache.UMemcacheCache',
        'LOCATION': private.CACHES_DEFAULT_LOCATION,
        'TIMEOUT': 500,
        'KEY_PREFIX': CACHE_PREFIX,
        'OPTIONS': {
            'MAX_POOL_SIZE': '15',
            'BLACKLIST_TIME': 60,
            'SOCKET_TIMEOUT': 10},
    }, 
}

SECRET_KEY = private.SECRET_KEY

LOG_LEVEL = logging.DEBUG

## Celery
BROKER_HOST = private.BROKER_HOST
BROKER_PORT = private.BROKER_PORT
BROKER_USER = private.BROKER_USER
BROKER_PASSWORD = private.BROKER_PASSWORD
BROKER_VHOST = private.BROKER_VHOST
CELERY_IGNORE_RESULT = True
CELERY_DISABLE_RATE_LIMITS = True
CELERYD_PREFETCH_MULTIPLIER = 1

NETAPP_BASE = private.NETAPP_STORAGE_ROOT
NETAPP_STORAGE = NETAPP_BASE + '/shared_storage'
MIRROR_STAGE_PATH = NETAPP_BASE + '/public-staging'
GUARDED_ADDONS_PATH = NETAPP_BASE + '/guarded-addons'
WATERMARKED_ADDONS_PATH = NETAPP_BASE + '/watermarked-addons'
UPLOADS_PATH = NETAPP_STORAGE + '/uploads'
USERPICS_PATH = UPLOADS_PATH + '/userpics'
ADDON_ICONS_PATH = UPLOADS_PATH + '/addon_icons'
COLLECTIONS_ICON_PATH = UPLOADS_PATH + '/collection_icons'
IMAGEASSETS_PATH = UPLOADS_PATH + '/imageassets'
IMAGEASSET_FULL_PATH = IMAGEASSETS_PATH + '/%s/%d.%s'
PERSONAS_PATH = UPLOADS_PATH + '/personas'
PREVIEWS_PATH = UPLOADS_PATH + '/previews'
PREVIEW_THUMBNAIL_PATH = PREVIEWS_PATH + '/thumbs/%s/%d.png'
PREVIEW_FULL_PATH = PREVIEWS_PATH + '/full/%s/%d.png'
ADDONS_PATH = NETAPP_BASE + '/files'

HERA = []
LOGGING['loggers'].update({
    'z.task': { 'level': logging.DEBUG },
    'z.hera': { 'level': logging.INFO },
    'z.redis': { 'level': logging.DEBUG },
    'z.pool': { 'level': logging.ERROR },
})


REDIS_BACKEND = private.REDIS_BACKENDS_CACHE
REDIS_BACKENDS = {
    'cache': REDIS_BACKEND,
    'cache_slave': private.REDIS_BACKENDS_CACHE_SLAVE,
    'master': private.REDIS_BACKENDS_MASTER,
    'slave': private.REDIS_BACKENDS_SLAVE,
}
CACHE_MACHINE_USE_REDIS = True

RECAPTCHA_PUBLIC_KEY = private.RECAPTCHA_PUBLIC_KEY
RECAPTCHA_PRIVATE_KEY = private.RECAPTCHA_PRIVATE_KEY
RECAPTCHA_URL = ('https://www.google.com/recaptcha/api/challenge?k=%s' % RECAPTCHA_PUBLIC_KEY)

CSP_FRAME_SRC = ("'self'", "https://sandbox.paypal.com",)

TMP_PATH = os.path.join(NETAPP_STORAGE, 'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')


SPHINX_CATALOG_PATH = TMP_PATH + '/data/sphinx'
SPHINX_LOG_PATH = TMP_PATH + '/log/searchd'

PERF_THRESHOLD = 20

SPIDERMONKEY = '/usr/bin/tracemonkey'

# Remove DetectMobileMiddleware from middleware in production.
detect = 'mobility.middleware.DetectMobileMiddleware'
csp = 'csp.middleware.CSPMiddleware'


RESPONSYS_ID = private.RESPONSYS_ID

CRONJOB_LOCK_PREFIX = 'addons-stage'

BUILDER_ROOT_URL = 'https://builder-addons.allizom.org'
BUILDER_SECRET_KEY = private.BUILDER_SECRET_KEY
BUILDER_VERSIONS_URL = BUILDER_ROOT_URL + "/repackage/sdk-versions/"

ES_HOSTS = private.ES_HOSTS
ES_INDEXES = {'default': 'addons_stage',
              'update_counts': 'addons_stage_stats',
              'download_counts': 'addons_stage_stats'}

BUILDER_UPGRADE_URL = BUILDER_ROOT_URL + "/repackage/rebuild/"

STATSD_HOST = private.STATSD_HOST
STATSD_PORT = private.STATSD_PORT

GRAPHITE_HOST = private.GRAPHITE_HOST
GRAPHITE_PORT = private.GRAPHITE_PORT


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

AMO_LANGUAGES = AMO_LANGUAGES + ('dbg',)

# :-(
def lazy_langs():
    from product_details import product_details
    if not product_details.languages:
        return {}
    return dict([(i.lower(), product_details.languages[i]['native'])
                 for i in AMO_LANGUAGES])


LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])
LANGUAGES = lazy(lazy_langs, dict)()
