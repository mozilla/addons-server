from lib.settings_base import *
from mkt.settings import *
from settings_base import *

from .. import splitstrip
import private_mkt

DOMAIN = 'marketplace.firefox.com'
SERVER_EMAIL = 'zmarketplaceprod@addons.mozilla.org'
SECRET_KEY = private_mkt.SECRET_KEY

DOMAIN = 'marketplace.firefox.com'
SITE_URL = 'https://marketplace.firefox.com'
SERVICES_URL = SITE_URL
STATIC_URL = 'https://marketplace.cdn.mozilla.net/'
LOCAL_MIRROR_URL = '%s_files' % STATIC_URL
MIRROR_URL = LOCAL_MIRROR_URL
INAPP_IMAGE_URL = '%sinapp-image' % STATIC_URL

CSP_STATIC_URL = STATIC_URL[:-1]
CSP_IMG_SRC = CSP_IMG_SRC + (CSP_STATIC_URL,)
CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (CSP_STATIC_URL,)
CSP_STYLE_SRC = CSP_STYLE_SRC + (CSP_STATIC_URL,)

ADDON_ICON_URL = STATIC_URL + 'img/uploads/addon_icons/%s/%s-%s.png?modified=%s'
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        'img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (STATIC_URL +
        'img/uploads/previews/full/%s/%d.%s?modified=%d')
# paths for uploaded extensions
FILES_URL = STATIC_URL + "%s/%s/downloads/file/%d/%s?src=%s"

PREVIEW_FULL_PATH = PREVIEWS_PATH + '/full/%s/%d.%s'

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

# paths for uploaded extensions
IMAGEASSET_FULL_URL = STATIC_URL + 'img/uploads/imageassets/%s/%d.png?modified=%d'
USERPICS_URL = STATIC_URL + 'img/uploads/userpics/%s/%s/%s.png?modified=%d'
COLLECTION_ICON_URL = STATIC_URL + 'img/uploads/collection_icons/%s/%s.png?m=%s'


MEDIA_URL = STATIC_URL + 'media/'
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + 'img/hub'
ADDON_ICON_BASE_URL = MEDIA_URL + 'img/icons/'

CACHE_PREFIX = 'marketplace.%s' % CACHE_PREFIX
CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX

SYSLOG_TAG = "http_app_addons_marketplace"
SYSLOG_TAG2 = "http_app_addons_marketplace_timer"
SYSLOG_CSP = "http_app_addons_marketplace_csp"

## Celery
BROKER_HOST = private_mkt.BROKER_HOST
BROKER_PORT = private_mkt.BROKER_PORT
BROKER_USER = private_mkt.BROKER_USER
BROKER_PASSWORD = private_mkt.BROKER_PASSWORD
BROKER_VHOST = private_mkt.BROKER_VHOST
CELERYD_PREFETCH_MULTIPLIER = 1

LOGGING['loggers'].update({
    'z.task': { 'level': logging.DEBUG },
    'z.hera': { 'level': logging.INFO },
    'z.redis': { 'level': logging.DEBUG },
    'z.receipt': {'level': logging.ERROR },
})

PAYPAL_APP_ID = private_mkt.PAYPAL_APP_ID
PAYPAL_EMBEDDED_AUTH = {
    'USER': private_mkt.PAYPAL_EMBEDDED_AUTH_USER,
    'PASSWORD': private_mkt.PAYPAL_EMBEDDED_PASSWORD,
    'SIGNATURE': private_mkt.PAYPAL_EMBEDDED_SIGNATURE,
}

PAYPAL_CGI_AUTH = PAYPAL_EMBEDDED_AUTH
PAYPAL_CHAINS = (
    (30, private_mkt.PAYPAL_CHAINS_EMAIL),
)


CRONJOB_LOCK_PREFIX = 'addons'

STATSD_PREFIX = 'addons-marketplace'

GRAPHITE_PREFIX = STATSD_PREFIX

CEF_PRODUCT = STATSD_PREFIX


IMPALA_BROWSE = True
IMPALA_REVIEWS = True

WEBAPPS_RECEIPT_KEY = private_mkt.WEBAPPS_RECEIPT_KEY
WEBAPPS_RECEIPT_URL = private_mkt.WEBAPPS_RECEIPT_URL

APP_PREVIEW = True
MIDDLEWARE_CLASSES = tuple(m for m in MIDDLEWARE_CLASSES if m not in (csp,))

WEBAPPS_UNIQUE_BY_DOMAIN = True

WAFFLE_SUFFIX = WAFFLE_TABLE_SUFFIX = 'mkt'

SENTRY_DSN = private_mkt.SENTRY_DSN

METRICS_SERVER = 'https://data.mozilla.com/'

INAPP_KEY_PATHS = {'2012-05-09': private_mkt.INAPP_KEY_PATH}

# Bug 748403
SIGNING_SERVER = private_mkt.SIGNING_SERVER
SIGNING_SERVER_ACTIVE = True

# Bug 793876
SIGNED_APPS_SERVER_ACTIVE = True
SIGNED_APPS_SERVER = private_mkt.SIGNED_APPS_SERVER
SIGNED_APPS_REVIEWER_SERVER_ACTIVE = True
SIGNED_APPS_REVIEWER_SERVER = private_mkt.SIGNED_APPS_REVIEWER_SERVER

CARRIER_URLS = splitstrip(private_mkt.CARRIER_URLS)

SENTRY_CLIENT = 'djangoraven.metlog.MetlogDjangoClient'

# Pass through the DSN to the Raven client and force signal
# registration so that exceptions are passed through to sentry
RAVEN_CONFIG = {'dsn': SENTRY_DSN, 'register_signals': True}

METLOG_CONF = {
    'plugins': {'cef': ('metlog_cef.cef_plugin:config_plugin', {}),
                'raven': (
                    'metlog_raven.raven_plugin:config_plugin', {'dsn': SENTRY_DSN}),
        },
    'sender': {
        'class': 'metlog.senders.UdpSender',
        'host': splitstrip(private.METLOG_CONF_SENDER_HOST),
        'port': private.METLOG_CONF_SENDER_PORT,
    },
    'logger': 'addons-marketplace-prod',
}
METLOG = client_from_dict_config(METLOG_CONF)
USE_METLOG_FOR_CEF = True
USE_METLOG_FOR_TASTYPIE = True
