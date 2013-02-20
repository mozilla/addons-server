"""private_addons will be populated from puppet and placed in this directory"""

from lib.settings_base import *
from default.settings import *
from settings_base import *

import private_addons

DOMAIN = 'addons.allizom.org'
SERVER_EMAIL = 'zstage@addons.mozilla.org'

SITE_URL = 'https://addons.allizom.org'
SERVICES_URL = SITE_URL
STATIC_URL = 'https://addons-stage-cdn.allizom.org/'
LOCAL_MIRROR_URL = '%s_files' % STATIC_URL
MIRROR_URL = LOCAL_MIRROR_URL

CSP_IMG_SRC = CSP_IMG_SRC + (STATIC_URL,)
CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (STATIC_URL,)
CSP_STYLE_SRC = CSP_STYLE_SRC + (STATIC_URL,)

ADDON_ICON_URL = STATIC_URL + 'img/uploads/addon_icons/%s/%s-%s.png?modified=%s'
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        'img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (STATIC_URL +
        'img/uploads/previews/full/%s/%d.png?modified=%d')
# paths for uploaded extensions
FILES_URL = STATIC_URL + "%s/%s/downloads/file/%d/%s?src=%s"

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

# paths for uploaded extensions
IMAGEASSET_FULL_URL = STATIC_URL + 'img/uploads/imageassets/%s/%d.png?modified=%d'
USERPICS_URL = STATIC_URL + 'img/uploads/userpics/%s/%s/%s.png?modified=%d'
COLLECTION_ICON_URL = STATIC_URL + '/img/uploads/collection_icons/%s/%s.png?m=%s'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = private_addons.EMAIL_HOST

MEDIA_URL = STATIC_URL + 'media/'
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + 'img/addon-icons'
ADDON_ICON_BASE_URL = MEDIA_URL + 'img/icons/'


CACHE_PREFIX = 'stage.%s' % CACHE_PREFIX
KEY_PREFIX = CACHE_PREFIX
CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX
STATSD_PREFIX = 'addons-stage'
GRAPHITE_PREFIX = STATSD_PREFIX
CEF_PRODUCT = STATSD_PREFIX



SYSLOG_TAG = "http_app_addons_stage"
SYSLOG_TAG2 = "http_app_addons_stage_timer"
SYSLOG_CSP = "http_app_addons_stage_csp"

# sandbox
PAYPAL_PAY_URL = 'https://svcs.sandbox.paypal.com/AdaptivePayments/'
PAYPAL_FLOW_URL = 'https://sandbox.paypal.com/webapps/adaptivepayment/flow/pay'
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


CSP_FRAME_SRC = ("'self'", "https://sandbox.paypal.com",)

TMP_PATH = os.path.join(NETAPP_STORAGE, 'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')


WEBAPPS_RECEIPT_KEY = private_addons.WEBAPPS_RECEIPT_KEY

GOOGLE_ANALYTICS_DOMAIN = 'addons.mozilla.org'
