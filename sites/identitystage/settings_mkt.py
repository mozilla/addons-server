"""private_mkt will be populated from puppet and placed in this directory"""

from lib.settings_base import *
from mkt.settings import *
from settings_base import *

import private_mkt

DOMAIN = 'identity-stage-marketplace.allizom.org'
SERVER_EMAIL = 'zmarketplacestage@addons.mozilla.org'

SITE_URL = 'https://identity-stage-marketplace.allizom.org'
SERVICES_URL = SITE_URL
STATIC_URL = 'https://identity-stage-marketplace-cdn.allizom.org/'
LOCAL_MIRROR_URL = '%s_files' % STATIC_URL
MIRROR_URL = LOCAL_MIRROR_URL

CSP_STATIC_URL = STATIC_URL[:-1]
CSP_IMG_SRC = CSP_IMG_SRC + (CSP_STATIC_URL,)
CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (CSP_STATIC_URL,)
CSP_STYLE_SRC = CSP_STYLE_SRC + (CSP_STATIC_URL,)

BROWSERID_DOMAIN = 'login.anosrep.org'
BROWSERID_VERIFICATION_URL = 'https://verifier.login.anosrep.org/verify'
BROWSERID_JS_URL = 'https://login.anosrep.org/include.js'
NATIVE_BROWSERID_DOMAIN = 'firefoxos.anosrep.org'
UNVERIFIED_ISSUER = 'firefoxos.anosrep.org'

# This is a B2G (or other native) verifier. Adjust accordingly.
NATIVE_BROWSERID_VERIFICATION_URL = ('https://%s/verify'
                                             % NATIVE_BROWSERID_DOMAIN)
NATIVE_BROWSERID_JS_URL = ('https://%s/include.js'
                                   % NATIVE_BROWSERID_DOMAIN)


ADDON_ICON_URL = "%s/%s/%s/images/addon_icon/%%d-%%d.png?modified=%%s" % (STATIC_URL, LANGUAGE_CODE, DEFAULT_APP)
ADDON_ICON_URL = STATIC_URL + 'img/uploads/addon_icons/%s/%s-%s.png?modified=%s'
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        'img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (STATIC_URL +
        'img/uploads/previews/full/%s/%d.%s?modified=%d')
# paths for uploaded extensions
FILES_URL = STATIC_URL + "%s/%s/downloads/file/%d/%s?src=%s"

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

# paths for uploaded extensions
USERPICS_URL = STATIC_URL + 'img/uploads/userpics/%s/%s/%s.png?modified=%d'
COLLECTION_ICON_URL = STATIC_URL + '/img/uploads/collection_icons/%s/%s.png?m=%s'

MEDIA_URL = STATIC_URL + 'media/'
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + 'img/hub'
ADDON_ICON_BASE_URL = MEDIA_URL + 'img/icons/'
PRODUCT_ICON_URL = STATIC_URL + 'product-icons'

CACHE_PREFIX = 'identity.stage.mkt.%s' % CACHE_PREFIX
CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX

CACHES['default']['KEY_PREFIX'] = CACHE_PREFIX


LOG_LEVEL = logging.DEBUG
# The django statsd client to use, see django-statsd for more.
STATSD_CLIENT = 'django_statsd.clients.moz_metlog'

SYSLOG_TAG = "http_app_marketplace_identity_stage"
SYSLOG_TAG2 = "http_app_marketplace_identity_stage_timer"
SYSLOG_CSP = "http_app_marketplace_identity_stage_csp"
STATSD_PREFIX = 'marketplace-identity-stage'

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

PAYPAL_CGI_AUTH = { 'USER': private_mkt.PAYPAL_CGI_AUTH_USER,
                    'PASSWORD': private_mkt.PAYPAL_CGI_AUTH_PASSWORD,
                    'SIGNATURE': private_mkt.PAYPAL_CGI_AUTH_SIGNATURE,
}

PAYPAL_CHAINS = (
    (30, private_mkt.PAYPAL_CHAINS_EMAIL),
)

PAYPAL_LIMIT_PREAPPROVAL = False

WEBAPPS_RECEIPT_KEY = private_mkt.WEBAPPS_RECEIPT_KEY
WEBAPPS_RECEIPT_URL = private_mkt.WEBAPPS_RECEIPT_URL

APP_PREVIEW = True

WEBAPPS_UNIQUE_BY_DOMAIN = True

SENTRY_DSN = private_mkt.SENTRY_DSN

SOLITUDE_HOSTS = ('https://payments.allizom.org',)
SOLITUDE_OAUTH = {'key': private_mkt.SOLITUDE_OAUTH_KEY,
                  'secret': private_mkt.SOLITUDE_OAUTH_SECRET}

WEBAPPS_PUBLIC_KEY_DIRECTORY = NETAPP_STORAGE + '/public_keys'
PRODUCT_ICON_PATH = NETAPP_STORAGE + '/product-icons'
DUMPED_APPS_PATH = NETAPP_STORAGE + '/dumped-apps'
DUMPED_USERS_PATH = NETAPP_STORAGE + '/dumped-users'

GOOGLE_ANALYTICS_DOMAIN = 'marketplace.firefox.com'
VALIDATOR_IAF_URLS = ['https://marketplace.firefox.com',
                      'https://marketplace.allizom.org',
                      'https://identity-stage-marketplace.allizom.org',
                      'https://marketplace-dev.allizom.org',
                      'https://marketplace-altdev.allizom.org']

if getattr(private_mkt, 'LOAD_TESTING', False):
    # mock the authentication and use django_fakeauth for this
    AUTHENTICATION_BACKENDS = ('django_fakeauth.FakeAuthBackend',)\
                              + AUTHENTICATION_BACKENDS
    MIDDLEWARE_CLASSES.insert(
            MIDDLEWARE_CLASSES.index('access.middleware.ACLMiddleware'),
            'django_fakeauth.FakeAuthMiddleware')
    FAKEAUTH_TOKEN = private_mkt.FAKEAUTH_TOKEN

    # we are also creating access tokens for OAuth, here are the keys and
    # secrets used for them
    API_PASSWORD = getattr(private_mkt, 'API_PASSWORD', FAKEAUTH_TOKEN)
AMO_LANGUAGES = AMO_LANGUAGES + ('dbg',)
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])

BLUEVIA_SECRET = private_mkt.BLUEVIA_SECRET

#Bug 748403
SIGNING_SERVER = private_mkt.SIGNING_SERVER
SIGNING_SERVER_ACTIVE = True
SIGNING_VALID_ISSUERS = ['identity-stage-marketplace-cdn.allizom.org']

#Bug 793876
SIGNED_APPS_KEY = private_mkt.SIGNED_APPS_KEY
SIGNED_APPS_SERVER_ACTIVE = True
SIGNED_APPS_SERVER = private_mkt.SIGNED_APPS_SERVER
SIGNED_APPS_REVIEWER_SERVER_ACTIVE = True
SIGNED_APPS_REVIEWER_SERVER = private_mkt.SIGNED_APPS_REVIEWER_SERVER

METLOG_CONF = {
    'plugins': {'cef': ('metlog_cef.cef_plugin:config_plugin', {
                        'syslog_facility': 'LOCAL4',
                        # CEF_PRODUCT is defined in settings_base
                        'syslog_ident': CEF_PRODUCT,
                        'syslog_priority': 'INFO'
                        }),
                'raven': (
                    'metlog_raven.raven_plugin:config_plugin', {'dsn': SENTRY_DSN}),
        },
    'sender': {
        'class': 'metlog.senders.UdpSender',
        'host': splitstrip(private.METLOG_CONF_SENDER_HOST),
        'port': private.METLOG_CONF_SENDER_PORT,
    },
    'logger': 'marketplace-identity-stage',
}
METLOG = client_from_dict_config(METLOG_CONF)
USE_METLOG_FOR_CEF = True
SENTRY_CLIENT = 'djangoraven.metlog.MetlogDjangoClient'

# See mkt/settings.py for more info.
APP_PURCHASE_KEY = DOMAIN
APP_PURCHASE_AUD = DOMAIN
APP_PURCHASE_TYP = 'mozilla-stage/payments/pay/v1'
APP_PURCHASE_SECRET = private_mkt.APP_PURCHASE_SECRET

MONOLITH_PASSWORD = private_mkt.MONOLITH_PASSWORD

# This is mainly for Marionette tests.
WEBAPP_MANIFEST_NAME = 'Marketplace Identity Stage'

ENABLE_API_ERROR_SERVICE = True

ES_USE_PLUGINS = True
