"""private_addons will be populated from puppet and placed in this directory"""

from lib.settings_base import *
from default.settings import *
from settings_base import *

import private_addons

DOMAIN = 'addons-dev.allizom.org'
SERVER_EMAIL = 'zdev@addons.mozilla.org'

SITE_URL = 'https://addons-dev.allizom.org'
SERVICES_URL = SITE_URL
STATIC_URL = 'https://addons-dev-cdn.allizom.org/'
LOCAL_MIRROR_URL = '%s_files' % STATIC_URL
MIRROR_URL = STATIC_URL + 'storage/public-staging'

CSP_STATIC_URL = STATIC_URL[:-1]
CSP_IMG_SRC = CSP_IMG_SRC + (CSP_STATIC_URL,)
CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (CSP_STATIC_URL,)
CSP_STYLE_SRC = CSP_STYLE_SRC + (CSP_STATIC_URL,)
CSP_FRAME_SRC = ("'self'", "https://sandbox.paypal.com",)

ADDON_ICON_URL = STATIC_URL + 'img/uploads/addon_icons/%s/%s-%s.png?modified=%s'
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        'img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (STATIC_URL +
        'img/uploads/previews/full/%s/%d.png?modified=%d')
NEW_PERSONAS_IMAGE_URL = STATIC_URL + 'img/uploads/themes/%(id)d/%(file)s'

# paths for uploaded extensions
FILES_URL = STATIC_URL + "%s/%s/downloads/file/%d/%s?src=%s"

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

IMAGEASSET_FULL_URL = STATIC_URL + 'img/uploads/imageassets/%s/%d.png?modified=%d'
USERPICS_URL = STATIC_URL + 'img/uploads/userpics/%s/%s/%s.png?modified=%d'
COLLECTION_ICON_URL = STATIC_URL + '/img/uploads/collection_icons/%s/%s.png?m=%s'

NEW_PERSONAS_IMAGE_URL = STATIC_URL + 'img/uploads/themes/%(id)d/%(file)s'

MEDIA_URL = STATIC_URL + 'media/'
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + 'img/addon-icons'
ADDON_ICON_BASE_URL = MEDIA_URL + 'img/icons/'


CACHE_PREFIX = 'dev.%s' % CACHE_PREFIX
KEY_PREFIX = CACHE_PREFIX
CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX
CACHES['default']['KEY_PREFIX'] = CACHE_PREFIX

SYSLOG_TAG = "http_app_addons_dev"
SYSLOG_TAG2 = "http_app_addons_dev_timer"
SYSLOG_CSP = "http_app_addons_dev_csp"

# sandbox
PAYPAL_PAY_URL = 'https://svcs.sandbox.paypal.com/AdaptivePayments/'
PAYPAL_FLOW_URL = 'https://www.sandbox.paypal.com/webapps/adaptivepayment/flow/pay'
PAYPAL_API_URL = 'https://api-3t.sandbox.paypal.com/nvp'
PAYPAL_EMAIL = private_addons.PAYPAL_EMAIL
PAYPAL_APP_ID = private_addons.PAYPAL_APP_ID
PAYPAL_PERMISSIONS_URL = 'https://svcs.sandbox.paypal.com/Permissions/'
PAYPAL_CGI_URL = 'https://www.sandbox.paypal.com/cgi-bin/webscr'
PAYPAL_EMBEDDED_AUTH = {
    'USER': private_addons.PAYPAL_EMBEDDED_AUTH_USER,
    'PASSWORD': private_addons.PAYPAL_EMBEDDED_AUTH_PASSWORD,
    'SIGNATURE': private_addons.PAYPAL_EMBEDDED_AUTH_SIGNATURE,
}
PAYPAL_CGI_AUTH = { 'USER': private_addons.PAYPAL_CGI_AUTH_USER,
                    'PASSWORD': private_addons.PAYPAL_CGI_AUTH_PASSWORD,
                    'SIGNATURE': private_addons.PAYPAL_CGI_AUTH_SIGNATURE,
}

PAYPAL_CHAINS = (
    (30, private_addons.PAYPAL_CHAINS_EMAIL),
)

WEBAPPS_RECEIPT_KEY = private_addons.WEBAPPS_RECEIPT_KEY
WEBAPPS_UNIQUE_BY_DOMAIN = False

SENTRY_DSN = private_addons.SENTRY_DSN

AMO_LANGUAGES = AMO_LANGUAGES + ('dbg',)
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])

METLOG_CONF = {
    'plugins': {'cef': ('metlog_cef.cef_plugin:config_plugin', {}),
                'raven': (
                    'metlog_raven.raven_plugin:config_plugin', {'dsn': private_addons.SENTRY_DSN}),
        },
    'sender': {
        'class': 'metlog.senders.UdpSender',
        'host': splitstrip(private.METLOG_CONF_SENDER_HOST),
        'port': private.METLOG_CONF_SENDER_PORT,
    },
    'logger': 'addons-dev',
}

METLOG = client_from_dict_config(METLOG_CONF)

USE_METLOG_FOR_CEF = True
USE_METLOG_FOR_TASTYPIE = False

GOOGLE_ANALYTICS_DOMAIN = 'addons.mozilla.org'
