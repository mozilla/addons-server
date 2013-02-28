"""private_mkt will be populated from puppet and placed in this directory"""

from lib.settings_base import *
from mkt.settings import *
from settings_base import *

import private_mkt

DOMAIN = 'marketplace-dev.allizom.org'
SERVER_EMAIL = 'zmarketplacedev@addons.mozilla.org'

SITE_URL = 'https://marketplace-dev.allizom.org'
SERVICES_URL = SITE_URL
STATIC_URL = 'https://marketplace-dev-cdn.allizom.org/'
LOCAL_MIRROR_URL = '%s_files' % STATIC_URL
MIRROR_URL = LOCAL_MIRROR_URL

CSP_STATIC_URL = STATIC_URL[:-1]
CSP_IMG_SRC = CSP_IMG_SRC + (CSP_STATIC_URL,)
CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (CSP_STATIC_URL,)
CSP_STYLE_SRC = CSP_STYLE_SRC + (CSP_STATIC_URL,)
CSP_FONT_SRC = CSP_FONT_SRC + (CSP_STATIC_URL,)

ADDON_ICON_URL = "%s/%s/%s/images/addon_icon/%%d-%%d.png?modified=%%s" % (
    STATIC_URL, LANGUAGE_CODE, DEFAULT_APP)
ADDON_ICON_URL = STATIC_URL + 'img/uploads/addon_icons/%s/%s-%s.png?modified=%s'
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        'img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (STATIC_URL +
        'img/uploads/previews/full/%s/%d.%s?modified=%d')
# paths for uploaded extensions
FILES_URL = STATIC_URL + "%s/%s/downloads/file/%d/%s?src=%s"

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

# paths for uploaded extensions
IMAGEASSET_FULL_URL = STATIC_URL + 'img/uploads/imageassets/%s/%d.png?modified=%d'
USERPICS_URL = STATIC_URL + 'img/uploads/userpics/%s/%s/%s.png?modified=%d'
COLLECTION_ICON_URL = STATIC_URL + '/img/uploads/collection_icons/%s/%s.png?m=%s'

MEDIA_URL = STATIC_URL + 'media/'
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + 'img/hub'
ADDON_ICON_BASE_URL = MEDIA_URL + 'img/icons/'

INAPP_IMAGE_URL = STATIC_URL + 'inapp-image'


CACHE_PREFIX = 'dev.mkt.%s' % CACHE_PREFIX
CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX
CACHES['default']['KEY_PREFIX'] = CACHE_PREFIX

SYSLOG_TAG = "http_app_addons_marketplacedev"
SYSLOG_TAG2 = "http_app_addons_marketplacedev_timer"
SYSLOG_CSP = "http_app_addons_marketplacedev_csp"

STATSD_PREFIX = 'addons-marketplacedev'

## Celery
BROKER_URL = private_mkt.BROKER_URL
CELERY_IGNORE_RESULT = True
CELERY_DISABLE_RATE_LIMITS = True
CELERYD_PREFETCH_MULTIPLIER = 1

# sandbox
PAYPAL_PAY_URL = 'https://svcs.sandbox.paypal.com/AdaptivePayments/'
PAYPAL_FLOW_URL = 'https://www.sandbox.paypal.com/webapps/adaptivepayment/flow/pay'
PAYPAL_API_URL = 'https://api-3t.sandbox.paypal.com/nvp'
PAYPAL_EMAIL = private_mkt.PAYPAL_EMAIL
PAYPAL_APP_ID = private_mkt.PAYPAL_APP_ID
PAYPAL_PERMISSIONS_URL = 'https://svcs.sandbox.paypal.com/Permissions/'
PAYPAL_CGI_URL = 'https://www.sandbox.paypal.com/cgi-bin/webscr'
PAYPAL_EMBEDDED_AUTH = {
    'USER': private_mkt.PAYPAL_EMBEDDED_AUTH_USER,
    'PASSWORD': private_mkt.PAYPAL_EMBEDDED_AUTH_PASSWORD,
    'SIGNATURE': private_mkt.PAYPAL_EMBEDDED_AUTH_SIGNATURE,
}

PAYPAL_CGI_AUTH = {
    'USER': private_mkt.PAYPAL_CGI_AUTH_USER,
    'PASSWORD': private_mkt.PAYPAL_CGI_AUTH_PASSWORD,
    'SIGNATURE': private_mkt.PAYPAL_CGI_AUTH_SIGNATURE,
}

PAYPAL_CHAINS = (
    (30, private_mkt.PAYPAL_CHAINS_EMAIL),
)

WEBAPPS_RECEIPT_KEY = private_mkt.WEBAPPS_RECEIPT_KEY
WEBAPPS_RECEIPT_URL = private_mkt.WEBAPPS_RECEIPT_URL

APP_PREVIEW = True

# Use HTML5 offline cache?
USE_APPCACHE = False

WEBAPPS_UNIQUE_BY_DOMAIN = False

#Bug 744268
INAPP_VERBOSE_ERRORS = True

INAPP_REQUIRE_HTTPS = False

SENTRY_DSN = private_mkt.SENTRY_DSN

#Bug 747548
METRICS_SERVER = 'https://data.mozilla.com/'

WEBAPPS_PUBLIC_KEY_DIRECTORY = NETAPP_STORAGE + '/public_keys'
INAPP_IMAGE_PATH = NETAPP_STORAGE + '/inapp-image'

INAPP_KEY_PATHS = private_mkt.INAPP_KEY_PATHS

SOLITUDE_HOSTS = ('https://payments-dev.allizom.org',)

PAYPAL_LIMIT_PREAPPROVAL = False

VALIDATOR_IAF_URLS = ['https://marketplace.firefox.com',
                      'https://marketplace.allizom.org',
                      'https://marketplace-dev.allizom.org']

# Override the limited marketplace ones with these ones from AMO. Because
# the base gets overridden in the mkt.settings file, we'll set them back again.
AMO_LANGUAGES = (
    'af', 'ar', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'en-US', 'es', 'eu', 'fa',
    'fi', 'fr', 'ga-IE', 'he', 'hu', 'id', 'it', 'ja', 'ko', 'mn', 'nl', 'pl',
    'pt-BR', 'pt-PT', 'ro', 'ru', 'sk', 'sl', 'sq', 'sv-SE', 'uk', 'vi',
    'zh-CN', 'zh-TW', 'dbg'  # Note the addition of dbg there.
)
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])
HIDDEN_LANGUAGES = (
    'cy', 'sr', 'sr-Latn', 'tr',
)

BLUEVIA_SECRET = private_mkt.BLUEVIA_SECRET

#Bug 748403
SIGNING_SERVER = private_mkt.SIGNING_SERVER
SIGNING_SERVER_ACTIVE = True

#Bug 793876
SIGNED_APPS_KEY = private_mkt.SIGNED_APPS_KEY
SIGNED_APPS_SERVER_ACTIVE = True
SIGNED_APPS_SERVER = private_mkt.SIGNED_APPS_SERVER
SIGNED_APPS_REVIEWER_SERVER_ACTIVE = True
SIGNED_APPS_REVIEWER_SERVER = private_mkt.SIGNED_APPS_REVIEWER_SERVER

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
    'logger': 'addons-marketplace-dev',
}
METLOG = client_from_dict_config(METLOG_CONF)
USE_METLOG_FOR_CEF = True
USE_METLOG_FOR_TASTYPIE = True

GOOGLE_ANALYTICS_DOMAIN = 'marketplace.firefox.com'

SENTRY_CLIENT = 'djangoraven.metlog.MetlogDjangoClient'

# Pass through the DSN to the Raven client and force signal
# registration so that exceptions are passed through to sentry
RAVEN_CONFIG = {'dsn': SENTRY_DSN, 'register_signals': True}

# See mkt/settings.py for more info.
APP_PURCHASE_KEY = DOMAIN
APP_PURCHASE_AUD = DOMAIN
APP_PURCHASE_TYP = 'mozilla-dev/payments/pay/v1'
APP_PURCHASE_SECRET = private_mkt.APP_PURCHASE_SECRET

# We upgraded to jQuery 1.9.1. Run this command to include jquery-migrate in the JS
# bundle to see which APIs and features were removed from jQuery core.
MINIFY_BUNDLES['js'].update(asset_bundles.jquery_migrated())

MONOLITH_PASSWORD = private_mkt.MONOLITH_PASSWORD
