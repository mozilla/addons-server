"""private_addons will be populated from puppet and placed in this directory"""

from lib.settings_base import *
from default.settings import *
from settings_base import *

import private_addons

DOMAIN = 'addons-altdev.allizom.org'
SERVER_EMAIL = 'zdev@addons.mozilla.org'

SITE_URL = 'https://addons-altdev.allizom.org'
SERVICES_URL = SITE_URL
STATIC_URL = 'https://addons-altdev-cdn.allizom.org/'
LOCAL_MIRROR_URL = '%s_files' % STATIC_URL
MIRROR_URL = STATIC_URL + 'storage/public-staging'

CSP_FRAME_SRC = CSP_FRAME_SRC + ("https://sandbox.paypal.com",)
CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (STATIC_URL[:-1],)

ADDON_ICON_URL = STATIC_URL + 'img/uploads/addon_icons/%s/%s-%s.png?modified=%s'
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        'img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (STATIC_URL +
        'img/uploads/previews/full/%s/%d.png?modified=%d')
NEW_PERSONAS_IMAGE_URL = STATIC_URL + 'img/uploads/themes/%(id)d/%(file)s'

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

USERPICS_URL = STATIC_URL + 'img/uploads/userpics/%s/%s/%s.png?modified=%d'
COLLECTION_ICON_URL = STATIC_URL + '/img/uploads/collection_icons/%s/%s.png?m=%s'

NEW_PERSONAS_IMAGE_URL = STATIC_URL + 'img/uploads/themes/%(id)d/%(file)s'

MEDIA_URL = STATIC_URL + 'media/'


CACHE_PREFIX = 'altdev.%s' % CACHE_PREFIX
KEY_PREFIX = CACHE_PREFIX
CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX
CACHES['default']['KEY_PREFIX'] = CACHE_PREFIX

SYSLOG_TAG = "http_app_addons_altdev"
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

SENTRY_DSN = private_addons.SENTRY_DSN

AMO_LANGUAGES = AMO_LANGUAGES + ('dbg',)
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])

GOOGLE_ANALYTICS_DOMAIN = 'addons.mozilla.org'
