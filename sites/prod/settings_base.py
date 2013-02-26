import logging
import os

from lib.settings_base import CACHE_PREFIX, KNOWN_PROXIES, LOGGING
from .. import splitstrip
import private_base as private

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = private.EMAIL_HOST

SEND_REAL_EMAIL = True

ENGAGE_ROBOTS = True
DEBUG = False
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = False
SESSION_COOKIE_SECURE = True
REDIRECT_SECRET_KEY = private.REDIRECT_SECRET_KEY

ADMINS = ()

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

SERVICES_DATABASE = {
    'NAME': private.SERVICES_DATABASE_NAME,
    'USER': private.SERVICES_DATABASE_USER,
    'PASSWORD': private.SERVICES_DATABASE_PASSWORD,
    'HOST': private.SERVICES_DATABASE_HOST,
}

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


## Celery
BROKER_HOST = private.BROKER_HOST
BROKER_PORT = private.BROKER_PORT
CELERY_IGNORE_RESULT = True
CELERY_DISABLE_RATE_LIMITS = True
BROKER_CONNECTION_TIMEOUT = 0.1

NETAPP_STORAGE_ROOT = private.NETAPP_STORAGE_ROOT
NETAPP_STORAGE = NETAPP_STORAGE_ROOT + '/shared_storage'
GUARDED_ADDONS_PATH = NETAPP_STORAGE_ROOT + '/guarded-addons'
MIRROR_STAGE_PATH = NETAPP_STORAGE_ROOT + '/public-staging'
UPLOADS_PATH = NETAPP_STORAGE + '/uploads'
WATERMARKED_ADDONS_PATH = NETAPP_STORAGE + '/watermarked-addons'
INAPP_IMAGE_PATH = NETAPP_STORAGE + '/inapp-image'
USERPICS_PATH = UPLOADS_PATH + '/userpics'
ADDON_ICONS_PATH = UPLOADS_PATH + '/addon_icons'
COLLECTIONS_ICON_PATH = UPLOADS_PATH + '/collection_icons'
IMAGEASSETS_PATH = UPLOADS_PATH + '/imageassets'
IMAGEASSET_FULL_PATH = IMAGEASSETS_PATH + '/%s/%d.%s'
PERSONAS_PATH = UPLOADS_PATH + '/themes'
PREVIEWS_PATH = UPLOADS_PATH + '/previews'
PREVIEW_THUMBNAIL_PATH = PREVIEWS_PATH + '/thumbs/%s/%d.png'
PREVIEW_FULL_PATH = PREVIEWS_PATH + '/full/%s/%d.png'
SIGNED_APPS_PATH = NETAPP_STORAGE + '/signed_apps'
SIGNED_APPS_REVIEWER_PATH = NETAPP_STORAGE + '/signed_apps_reviewer'

HERA = []

LOG_LEVEL = logging.DEBUG

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

TMP_PATH = os.path.join(NETAPP_STORAGE, 'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')
SPHINX_CATALOG_PATH = TMP_PATH + '/data/sphinx'
SPHINX_LOG_PATH = TMP_PATH + '/log/searchd'

ADDONS_PATH = NETAPP_STORAGE_ROOT + '/files'

PERF_THRESHOLD = None
PERF_TEST_URL = 'http://talos-addon-master1.amotest.scl1.mozilla.com/trigger/trigger.cgi'

SPIDERMONKEY = '/usr/bin/tracemonkey'

# Remove DetectMobileMiddleware from middleware in production.
detect = 'mobility.middleware.DetectMobileMiddleware'
csp = 'csp.middleware.CSPMiddleware'


RESPONSYS_ID = private.RESPONSYS_ID

CRONJOB_LOCK_PREFIX = 'addons'

BUILDER_SECRET_KEY = private.BUILDER_SECRET_KEY

ES_HOSTS = splitstrip(private.ES_HOSTS)
ES_INDEXES = {'default': 'addons',
              'update_counts': 'addons_stats',
              'download_counts': 'addons_stats'}

BUILDER_UPGRADE_URL = "https://builder.addons.mozilla.org/repackage/rebuild/"

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

EMAIL_BLACKLIST = private.EMAIL_BLACKLIST

NEW_FEATURES = True

CLEANCSS_BIN = 'cleancss'
UGLIFY_BIN = 'uglifyjs'

XSENDFILE_HEADER  = 'X-Accel-Redirect'

GOOGLE_ANALYTICS_CREDENTIALS = private.GOOGLE_ANALYTICS_CREDENTIALS
