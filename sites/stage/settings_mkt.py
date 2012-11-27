"""private_mkt will be populated from puppet and placed in this directory"""

from lib.settings_base import *
from mkt.settings import *
from settings_base import *

import private_mkt

SERVER_EMAIL = 'zmarketplacestage@addons.mozilla.org'

DOMAIN = "marketplace.allizom.org"
SITE_URL = 'https://marketplace.allizom.org'
SERVICES_URL = SITE_URL
STATIC_URL = 'https://marketplace-cdn.allizom.org/'
LOCAL_MIRROR_URL = '%s_files' % STATIC_URL
MIRROR_URL = LOCAL_MIRROR_URL

CSP_STATIC_URL = STATIC_URL[:-1]
CSP_IMG_SRC = CSP_IMG_SRC + (CSP_STATIC_URL,)
CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (CSP_STATIC_URL,)
CSP_STYLE_SRC = CSP_STYLE_SRC + (CSP_STATIC_URL,)

ADDON_ICON_URL = STATIC_URL + 'img/uploads/addon_icons/%s/%s-%s.png?modified=%s'
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        'img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (STATIC_URL +
        'img/uploads/previews/full/%s/%d.png?modified=%d')
# paths for uploaded extensions
FILES_URL = STATIC_URL + "%s/%s/downloads/file/%d/%s?src=%s"

PREVIEW_FULL_PATH = PREVIEWS_PATH + '/full/%s/%d.%s'
SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

# paths for uploaded extensions
IMAGEASSET_FULL_URL = STATIC_URL + 'img/uploads/imageassets/%s/%d.png?modified=%d'
USERPICS_URL = STATIC_URL + 'img/uploads/userpics/%s/%s/%s.png?modified=%d'
COLLECTION_ICON_URL = STATIC_URL + '/img/uploads/collection_icons/%s/%s.png?m=%s'

MEDIA_URL = STATIC_URL + 'media/'
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + 'img/hub'
ADDON_ICON_BASE_URL = MEDIA_URL + 'img/icons/'

CACHE_PREFIX = 'stage.mkt.%s' % CACHE_PREFIX
CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX

STATSD_PREFIX = 'addons-marketplace-stage'
GRAPHITE_PREFIX = STATSD_PREFIX
CEF_PRODUCT = STATSD_PREFIX

PYLIBMC_MIN_COMPRESS_LEN = 150 * 1024

LOG_LEVEL = logging.DEBUG

SYSLOG_TAG = "http_app_addons_marketplacestage"
SYSLOG_TAG2 = "http_app_addons_marketplacestage_timer"
SYSLOG_CSP = "http_app_addons_marketplacestage_csp"

## Celery
BROKER_HOST = private_mkt.BROKER_HOST
BROKER_PORT = private_mkt.BROKER_PORT
BROKER_USER = private_mkt.BROKER_USER
BROKER_PASSWORD = private_mkt.BROKER_PASSWORD
BROKER_VHOST = private_mkt.BROKER_VHOST
CELERY_IGNORE_RESULT = True
CELERY_DISABLE_RATE_LIMITS = True
CELERYD_PREFETCH_MULTIPLIER = 1

PAYPAL_APP_ID = private_mkt.PAYPAL_APP_ID
PAYPAL_EMBEDDED_AUTH = {
    'USER': private_mkt.PAYPAL_EMBEDDED_AUTH_USER,
    'PASSWORD': private_mkt.PAYPAL_EMBEDDED_AUTH_PASSWORD,
    'SIGNATURE': private_mkt.PAYPAL_EMBEDDED_AUTH_SIGNATURE,
}

PAYPAL_CGI_AUTH = PAYPAL_EMBEDDED_AUTH

PAYPAL_CHAINS = (
    (30, private_mkt.PAYPAL_CHAINS_EMAIL),
)

CSP_FRAME_SRC = ("'self'", "https://sandbox.paypal.com",)

TMP_PATH = os.path.join(NETAPP_STORAGE, 'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')

PERF_THRESHOLD = 20

WEBAPPS_RECEIPT_KEY = private_mkt.WEBAPPS_RECEIPT_KEY
WEBAPPS_RECEIPT_URL = private_mkt.WEBAPPS_RECEIPT_URL

CLEANCSS_BIN = 'cleancss'
UGLIFY_BIN = 'uglifyjs'

APP_PREVIEW = True

WEBAPPS_UNIQUE_BY_DOMAIN = True

WAFFLE_SUFFIX = WAFFLE_TABLE_SUFFIX = 'mkt'

SENTRY_DSN = private_mkt.SENTRY_DSN

METRICS_SERVER = 'https://data.mozilla.com/'
VALIDATOR_IAF_URLS = ['https://marketplace.firefox.com',
                      'https://marketplace.allizom.org',
                      'https://marketplace-dev.allizom.org']

SOLITUDE_HOSTS = ('https://payments.allizom.org',)

GEOIP_NOOP = 0

WEBTRENDS_USERNAME = private_mkt.WEBTRENDS_USERNAME
WEBTRENDS_PASSWORD = private_mkt.WEBTRENDS_PASSWORD
