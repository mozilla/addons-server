from lib.settings_base import *
from default.settings import *
from settings_base import *

import private_addons

DOMAIN = getattr(private_addons, 'DOMAIN', 'addons.mozilla.org')

SERVER_EMAIL = 'zprod@addons.mozilla.org'
SECRET_KEY = private_addons.SECRET_KEY

SITE_URL = getattr(private_addons, 'SITE_URL', 'https://' + DOMAIN)
SERVICES_URL = 'https://services.addons.mozilla.org'
STATIC_URL = getattr(private_addons, 'STATIC_URL', 'https://addons.cdn.mozilla.net/static/')
MEDIA_URL = getattr(private_addons, 'MEDIA_URL', 'https://addons.cdn.mozilla.net/user-media/')

CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (STATIC_URL[:-1],)
CSP_FRAME_SRC = ("'self'", "https://*.paypal.com",)

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN


CACHE_PREFIX = 'prod.amo.%s' % CACHE_PREFIX
CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX
CACHES['default']['KEY_PREFIX'] = CACHE_PREFIX

MIDDLEWARE_CLASSES = tuple(m for m in MIDDLEWARE_CLASSES if m not in (csp,))

SYSLOG_TAG = "http_app_addons"
SYSLOG_TAG2 = "http_app_addons_timer"
SYSLOG_CSP = "http_app_addons_addons_csp"

FETCH_BY_ID = True

PAYPAL_APP_ID = private_addons.PAYPAL_APP_ID
PAYPAL_EMBEDDED_AUTH = {
    'USER': private_addons.PAYPAL_EMBEDDED_AUTH_USER,
    'PASSWORD': private_addons.PAYPAL_EMBEDDED_PASSWORD,
    'SIGNATURE': private_addons.PAYPAL_EMBEDDED_SIGNATURE,
}

PAYPAL_CGI_AUTH = PAYPAL_EMBEDDED_AUTH

RESPONSYS_ID = private_addons.RESPONSYS_ID

#read_only_mode(globals())

STATSD_PREFIX = 'addons'

GRAPHITE_PREFIX = STATSD_PREFIX

VALIDATOR_TIMEOUT = 90

SENTRY_DSN = private_addons.SENTRY_DSN

if NEWRELIC_ENABLE:
    NEWRELIC_INI = '/etc/newrelic.d/addons.mozilla.org.ini'
