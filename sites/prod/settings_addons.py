from lib.settings_base import *
from default.settings import *
from settings_base import *

import private_addons

DOMAIN = 'addons.mozilla.org'

SERVER_EMAIL = 'zprod@addons.mozilla.org'
SECRET_KEY = private_addons.SECRET_KEY

SITE_URL = 'https://addons.mozilla.org'
LOCAL_MIRROR_URL = '%s/_files' % SITE_URL
SERVICES_URL = 'https://services.addons.mozilla.org'
STATIC_URL = 'https://addons.cdn.mozilla.net/'
MIRROR_URL = STATIC_URL + 'storage/public-staging'

CSP_STATIC_URL = STATIC_URL[:-1]
CSP_IMG_SRC = CSP_IMG_SRC + (CSP_STATIC_URL,)
CSP_SCRIPT_SRC = CSP_SCRIPT_SRC + (CSP_STATIC_URL,)
CSP_STYLE_SRC = CSP_STYLE_SRC + (CSP_STATIC_URL,)
CSP_FRAME_SRC = ("'self'", "https://sandbox.paypal.com",)

ADDON_ICON_URL = STATIC_URL + 'img/uploads/addon_icons/%s/%s-%s.png?modified=%s'
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        'img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = STATIC_URL + 'img/uploads/previews/full/%s/%d.png?modified=%d'

# paths for uploaded extensions
FILES_URL = STATIC_URL + "%s/%s/downloads/file/%d/%s?src=%s"

SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN

IMAGEASSET_FULL_URL = STATIC_URL + 'img/uploads/imageassets/%s/%d.png?modified=%d'
USERPICS_URL = STATIC_URL + 'img/uploads/userpics/%s/%s/%s.png?modified=%d'
COLLECTION_ICON_URL = STATIC_URL + 'img/uploads/collection_icons/%s/%s.png?m=%s'

NEW_PERSONAS_IMAGE_URL = STATIC_URL + 'img/uploads/themes/%(id)d/%(file)s'

MEDIA_URL = "%smedia/" % STATIC_URL
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + '/img/addon-icons'
ADDON_ICON_BASE_URL = MEDIA_URL + 'img/icons/'

IMAGEASSET_FULL_URL = STATIC_URL + 'img/uploads/imageassets/%s/%d.png?m=%d'

CACHE_PREFIX = 'prod.amo.%s' % CACHE_PREFIX
CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_PREFIX
CACHES['default']['KEY_PREFIX'] = CACHE_PREFIX

MIDDLEWARE_CLASSES = tuple(m for m in MIDDLEWARE_CLASSES if m not in (csp,))

SYSLOG_TAG = "http_app_addons"
SYSLOG_TAG2 = "http_app_addons_timer"
SYSLOG_CSP = "http_app_addons_addons_csp"

## Celery
BROKER_USER = private_addons.BROKER_USER
BROKER_PASSWORD = private_addons.BROKER_PASSWORD
BROKER_VHOST = private_addons.BROKER_VHOST

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

# Just need it to be set to *something* for now, to make monitoring happy
WEBAPPS_RECEIPT_KEY = '/data/www/addons.mozilla.org/zamboni/README.rst'

VALIDATOR_TIMEOUT = 90

SENTRY_DSN = private_addons.SENTRY_DSN
