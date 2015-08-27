"""private_addons will be populated from puppet and placed in this directory"""

from lib.settings_base import *  # noqa
from settings_base import *  # noqa

import private_addons

DOMAIN = 'addons.allizom.org'
SERVER_EMAIL = 'zstage@addons.mozilla.org'

SITE_URL = 'https://addons.allizom.org'
SERVICES_URL = SITE_URL
STATIC_URL = getattr(private_addons, 'STATIC_URL',
                     'https://addons-stage-cdn.allizom.org/static/')
MEDIA_URL = getattr(private_addons, 'MEDIA_URL',
                    'https://addons-stage-cdn.allizom.org/user-media/')

CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (STATIC_URL[:-1],)
CSP_FRAME_SRC = ("'self'", "https://sandbox.paypal.com",)

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN


CACHE_PREFIX = 'stage.%s' % CACHE_PREFIX
KEY_PREFIX = CACHE_PREFIX
CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX
STATSD_PREFIX = 'addons-stage'
GRAPHITE_PREFIX = STATSD_PREFIX
CEF_PRODUCT = STATSD_PREFIX


SYSLOG_TAG = "http_app_addons_stage"
SYSLOG_TAG2 = "http_app_addons_stage_timer"
SYSLOG_CSP = "http_app_addons_stage_csp"

# Signing
# bug 1197226
# SIGNING_SERVER = private_addons.SIGNING_SERVER
# PRELIMINARY_SIGNING_SERVER = private_addons.PRELIMINARY_SIGNING_SERVER

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
PAYPAL_CGI_AUTH = {'USER': private_addons.PAYPAL_CGI_AUTH_USER,
                   'PASSWORD': private_addons.PAYPAL_CGI_AUTH_PASSWORD,
                   'SIGNATURE': private_addons.PAYPAL_CGI_AUTH_SIGNATURE}

PAYPAL_CHAINS = (
    (30, private_addons.PAYPAL_CHAINS_EMAIL),
)

TMP_PATH = os.path.join(NETAPP_STORAGE, 'tmp')
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')


GOOGLE_ANALYTICS_DOMAIN = 'addons.mozilla.org'

NEWRELIC_INI = '/etc/newrelic.d/addons.allizom.org.ini'

SENTRY_DSN = private_addons.SENTRY_DSN
