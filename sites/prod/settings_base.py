import logging
import os

import dj_database_url

from lib.settings_base import CACHE_PREFIX, KNOWN_PROXIES, LOGGING, HOSTNAME

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

DATABASES = {}
DATABASES['default'] = dj_database_url.parse(private.DATABASES_DEFAULT_URL)
DATABASES['default']['ENGINE'] = 'mysql_pool'
DATABASES['default']['OPTIONS'] = {'init_command': 'SET storage_engine=InnoDB'}

DATABASES['slave'] = dj_database_url.parse(private.DATABASES_SLAVE_URL)
DATABASES['slave']['ENGINE'] = 'mysql_pool'
DATABASES['slave']['OPTIONS'] = {'init_command': 'SET storage_engine=InnoDB'}

DATABASE_POOL_ARGS = {
    'max_overflow': 10,
    'pool_size': 5,
    'recycle': 300
}

SERVICES_DATABASE = dj_database_url.parse(private.SERVICES_DATABASE_URL)

SLAVE_DATABASES = ['slave']

CACHES = {
    'default': {
        'BACKEND': 'caching.backends.memcached.MemcachedCache',
        'LOCATION': splitstrip(private.CACHES_DEFAULT_LOCATION),
        'TIMEOUT': 500,
        'KEY_PREFIX': CACHE_PREFIX,
    },
}


## Celery
BROKER_URL = private.BROKER_URL

CELERY_IGNORE_RESULT = True
CELERY_DISABLE_RATE_LIMITS = True
BROKER_CONNECTION_TIMEOUT = 0.1

NETAPP_STORAGE_ROOT = private.NETAPP_STORAGE_ROOT
NETAPP_STORAGE = NETAPP_STORAGE_ROOT + '/shared_storage'
GUARDED_ADDONS_PATH = NETAPP_STORAGE_ROOT + '/guarded-addons'
MIRROR_STAGE_PATH = NETAPP_STORAGE_ROOT + '/public-staging'
UPLOADS_PATH = NETAPP_STORAGE + '/uploads'
USERPICS_PATH = UPLOADS_PATH + '/userpics'
ADDON_ICONS_PATH = UPLOADS_PATH + '/addon_icons'
COLLECTION_ICONS_PATH = UPLOADS_PATH + '/collection_icons'
IMAGEASSETS_PATH = UPLOADS_PATH + '/imageassets'
REVIEWER_ATTACHMENTS_PATH = UPLOADS_PATH + '/reviewer_attachment'
PREVIEWS_PATH = UPLOADS_PATH + '/previews'
PREVIEW_THUMBNAIL_PATH = PREVIEWS_PATH + '/thumbs/%s/%d.png'
PREVIEW_FULL_PATH = PREVIEWS_PATH + '/full/%s/%d.png'
SIGNED_APPS_PATH = NETAPP_STORAGE + '/signed_apps'
SIGNED_APPS_REVIEWER_PATH = NETAPP_STORAGE + '/signed_apps_reviewer'

HERA = []

LOG_LEVEL = logging.DEBUG

LOGGING['loggers'].update({
    'amqp': {'level': logging.WARNING},
    'raven': {'level': logging.WARNING},
    'requests': {'level': logging.WARNING},
    'z.addons': {'level': logging.INFO},
    'z.task': {'level': logging.DEBUG},
    'z.hera': {'level': logging.INFO},
    'z.redis': {'level': logging.DEBUG},
    'z.pool': {'level': logging.ERROR},
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
ES_URLS = ['http://%s' % h for h in ES_HOSTS]
# ES_INDEXES doesn't change for prod.

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

XSENDFILE_HEADER = 'X-Accel-Redirect'

GOOGLE_ANALYTICS_CREDENTIALS = private.GOOGLE_ANALYTICS_CREDENTIALS
GOOGLE_API_CREDENTIALS = private.GOOGLE_API_CREDENTIALS

GEOIP_URL = 'http://geo.marketplace.firefox.com'

NEWRELIC_WHITELIST = ['web1.addons.phx1.mozilla.com',
                      'web10.addons.phx1.mozilla.com',
                      'web20.addons.phx1.mozilla.com',
                      'web1.mktweb.services.phx1.mozilla.com',
                      'web4.mktweb.services.phx1.mozilla.com']

NEWRELIC_ENABLE = HOSTNAME in NEWRELIC_WHITELIST

AES_KEYS = private.AES_KEYS
