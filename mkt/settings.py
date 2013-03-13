import datetime
import os

from lib.settings_base import *
from mkt import asset_bundles

ALLOWED_HOSTS += ['.firefox.com']
# We'll soon need a `settings_test_mkt` to override this.
APP_PREVIEW = True

WAFFLE_TABLE_SUFFIX = 'mkt'
LOG_TABLE_SUFFIX = '_mkt'
EVENT_TABLE_SUFFIX = '_mkt'

# So temporary. Allow us to link to new devhub URLs from `Addon.get_dev_url()`.
# Also used to determine if we add the /<app>/ to URLs.
MARKETPLACE = True

# 403 view to render for CSRF failures.
CSRF_FAILURE_VIEW = 'mkt.site.views.csrf_failure'

# Set log in/log out URLs for redirects to work.
LOGIN_URL = '/login'
LOGOUT_URL = '/logout'

# Let robots tear this place up.
ENGAGE_ROBOTS = True

# Support carrier URLs that prefix all other URLs, such as /telefonica/.
# NOTE: To set this to False, you need to do so in this file or copy over
# the conditional middleware removal below.
USE_CARRIER_URLS = True

# List of URL prefixes that will be interpretted as custom carrier stores.
# When a URL is prefixed with one of these values, the value will be
# available in mkt.carriers.get_carrier() and will be hidden from all other
# url resolvers.
CARRIER_URLS = ['telefonica']

MKT_FEEDBACK_EMAIL = 'apps-feedback@mozilla.com'
MKT_REVIEWERS_EMAIL = 'app-reviews@mozilla.org'
MKT_SENIOR_EDITORS_EMAIL = 'amo-admin-reviews@mozilla.org'
MKT_SUPPORT_EMAIL = 'marketplace-developer-support@mozilla.org'
MARKETPLACE_EMAIL = 'amo-marketplace@mozilla.org'
ABUSE_EMAIL = 'Firefox Marketplace <marketplace-abuse@mozilla.org>'
NOBODY_EMAIL = 'Firefox Marketplace <nobody@mozilla.org>'
DEFAULT_FROM_EMAIL = 'Firefox Marketplace <nobody@mozilla.org>'

# Default app name for our webapp as specified in `manifest.webapp`.
WEBAPP_MANIFEST_NAME = 'Firefox Marketplace'

ROOT_URLCONF = 'mkt.urls'

INSTALLED_APPS = list(INSTALLED_APPS)
INSTALLED_APPS.remove('api')
INSTALLED_APPS.remove('browse')
INSTALLED_APPS.remove('compat')
INSTALLED_APPS.remove('discovery')
INSTALLED_APPS.remove('devhub')
INSTALLED_APPS.remove('search')
INSTALLED_APPS = tuple(INSTALLED_APPS)

INSTALLED_APPS += (
    'devhub',  # Put here so helpers.py doesn't get loaded first.
    'django_appcache',
    'mkt.site',
    'mkt.account',
    'mkt.api',
    'mkt.browse',
    'mkt.detail',
    'mkt.developers',
    'mkt.ecosystem',
    'mkt.files',
    'mkt.home',
    'mkt.inapp_pay',
    'mkt.lookup',
    'mkt.monolith',
    'mkt.offline',
    'mkt.purchase',
    'mkt.ratings',
    'mkt.receipts',
    'mkt.reviewers',
    'mkt.search',
    'mkt.stats',
    'mkt.submit',
    'mkt.support',
    'mkt.themes',
    'mkt.zadmin',
    'mkt.webapps',
    'mkt.webpay',
)

# TODO: I want to get rid of these eventually but it breaks some junk now.
# MIDDLEWARE_CLASSES.remove('mobility.middleware.DetectMobileMiddleware')
# MIDDLEWARE_CLASSES.remove('mobility.middleware.XMobileMiddleware')
MIDDLEWARE_CLASSES = list(MIDDLEWARE_CLASSES)
if USE_CARRIER_URLS:
    MIDDLEWARE_CLASSES.insert(0,
        # This needs to come before CommonMiddleware so that APPEND_SLASH
        # is handled.
        'mkt.carriers.middleware.CarrierURLMiddleware',
    )

MIDDLEWARE_CLASSES.append('mkt.site.middleware.RequestCookiesMiddleware')

MIDDLEWARE_CLASSES.remove('amo.middleware.LocaleAndAppURLMiddleware')
MIDDLEWARE_CLASSES += [
    'mkt.site.middleware.RedirectPrefixedURIMiddleware',
    'mkt.site.middleware.LocaleMiddleware',

    'mkt.regions.middleware.RegionMiddleware',
    'mkt.fragments.middleware.VaryOnAJAXMiddleware',
    'mkt.site.middleware.DeviceDetectionMiddleware',
    'mkt.fragments.middleware.HijackRedirectMiddleware',
    'mkt.api.middleware.CORSMiddleware'
]

TEMPLATE_DIRS += (path('mkt/templates'), path('mkt/zadmin/templates'))
TEMPLATE_CONTEXT_PROCESSORS = list(TEMPLATE_CONTEXT_PROCESSORS)
TEMPLATE_CONTEXT_PROCESSORS.remove('amo.context_processors.global_settings')
TEMPLATE_CONTEXT_PROCESSORS.remove('amo.context_processors.app')
TEMPLATE_CONTEXT_PROCESSORS += [
    'mkt.site.context_processors.global_settings',
]
if USE_CARRIER_URLS:
    TEMPLATE_CONTEXT_PROCESSORS.extend([
        'mkt.carriers.context_processors.carrier_data',
    ])

# Tests.
NOSE_ARGS = [
    '--with-fixture-bundling',
    '--where=%s' % os.path.join(ROOT, 'mkt')
]

NO_ADDONS_MODULES = (
    'addons.views',
    'devhub.views.dashboard',  # The apps dashboard is a different view.
    'devhub.views.submit',  # Addon submit not ok, app submit a-ok.
    'browse.views.personas',
    'browse.views.extensions',
    'browse.views.language_tools',
    'browse.views.themes',
)

# Extend AMO's bundles. Sorry, folks. One day when admin goes away this
# will be easier.
MINIFY_BUNDLES['css'].update(asset_bundles.CSS)
MINIFY_BUNDLES['js'].update(asset_bundles.JS)

CELERY_ROUTES.update({
    # Devhub.
    'mkt.developers.tasks.validator': {'queue': 'devhub'},
    'mkt.developers.tasks.fetch_manifest': {'queue': 'devhub'},
    'mkt.developers.tasks.fetch_icon': {'queue': 'devhub'},
    'mkt.developers.tasks.file_validator': {'queue': 'devhub'},

    # Images.
    'mkt.developers.tasks.resize_icon': {'queue': 'images'},
    'mkt.developers.tasks.resize_preview': {'queue': 'images'},
})

# Paths.
ADDON_ICONS_DEFAULT_PATH = os.path.join(MEDIA_ROOT, 'img/hub')
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + '/img/hub'

# Directory path to where product images for in-app payments are stored.
INAPP_IMAGE_PATH = NETAPP_STORAGE + '/inapp-image'

# Base URL root to serve in-app product images from.
INAPP_IMAGE_URL = INAPP_IMAGE_PATH

# Tuple of (x, y) pixel sizes that an in-app product image should be
# resized to for display on the payment screen.
INAPP_IMAGE_SIZE = (150, 150)

# JWT identifier for this marketplace.
# This is used for in-app payments in two ways.
# 1. app must send JWTs with aud (the audience) set to this exact value.
# 2. apps will receive JWTs with iss (issuer) set to this value.
INAPP_MARKET_ID = 'marketplace.mozilla.org'

# If True, show verbose payment errors to developers.
# Consider this insecure.
INAPP_VERBOSE_ERRORS = False

# When False, the developer can toggle HTTPS on/off.
# This is useful for development and testing.
INAPP_REQUIRE_HTTPS = True

# Paths to key files for local AES encrypt/decrypt.
# Each dict key is a YYYY-MM-DD timestamp that we use to find the latest key.
INAPP_KEY_PATHS = {
    # This is a scratch key for local development.
    '2012-05-09': os.path.join(ROOT, 'mkt', 'inapp_pay', 'tests', 'resources',
                               'inapp-sample-pay.key')
}

STATSD_RECORD_KEYS = [
    'window.performance.timing.domComplete',
    'window.performance.timing.domInteractive',
    'window.performance.timing.domLoading',
    'window.performance.timing.loadEventEnd',
    'window.performance.timing.responseStart',
    'window.performance.timing.fragment.loaded',
    'window.performance.navigation.redirectCount',
    'window.performance.navigation.type',
]

PISTON_DISPLAY_ERRORS = False

# Key for signing requests to BlueVia for developer registration.
BLUEVIA_SECRET = ''
BLUEVIA_ORIGIN = 'https://opentel20.tidprojects.com'
BLUEVIA_URL = BLUEVIA_ORIGIN + '/en/mozilla/?req='

# Link to the appcache manifest (activate it) when True.
USE_APPCACHE = False

# These are absolute paths to add to the cache. Wildcards are not allowed here.
# These paths will be added as-is to the cache section.
APPCACHE_TO_CACHE = [
    '/offline/home'
]

APPCACHE_NET_PATHS = [
    '*'
]

APPCACHE_FALLBACK_PATHS = {}
for url in CARRIER_URLS:
    APPCACHE_FALLBACK_PATHS['/%s' % url] = '/offline/home'


# This callable yields paths relative to MEDIA_ROOT that you want to explicitly
# cache. The browser will load *all* of these URLs when your app first loads
# so be mindful to only list essential media files. The actual URL of the path
# to cache will be determined using MEDIA_URL.
# If you use wildcards here the real paths to the file(s) will be
# expanded using glob.glob()


def APPCACHE_MEDIA_TO_CACHE():
    from jingo_minify import helpers
    bundle = 'mkt/offline'

    # TODO(Kumar) refactor jingo-minify so we don't have to copy/paste this
    # logic.

    css_build_id = helpers.BUILD_ID_CSS
    bundle_full = "css:%s" % bundle
    if bundle_full in helpers.BUNDLE_HASHES:
        css_build_id = helpers.BUNDLE_HASHES[bundle_full]

    return (
        'css/%s-min.css?build=%s' % (bundle, css_build_id),
    )


# Are you working locally? place the following line in your settings_local:
# APPCACHE_MEDIA_TO_CACHE = APPCACHE_MEDIA_DEBUG

def APPCACHE_MEDIA_DEBUG():
    for f in list(asset_bundles.CSS['mkt/offline']):
        if f.endswith('.less'):
            yield f + '.css'
        else:
            yield f

# Allowed `installs_allowed_from` values for manifest validator.
VALIDATOR_IAF_URLS = ['https://marketplace.firefox.com']

# All JS vendor libraries in this list will be excluded from mozmarket.js.
# For example, if receiptverifier is broken and you need to disable it, add
# 'receiptverifier' to the list. See also mkt/site/views.py.
MOZMARKET_VENDOR_EXCLUDE = []

# When True, mozmarket.js will be served as minified JavaScript.
MINIFY_MOZMARKET = True

# GeoIP server settings
# This flag overrides the GeoIP server functions and will force the
# return of the GEOIP_DEFAULT_VAL
GEOIP_NOOP = 1
GEOIP_HOST = 'localhost'
GEOIP_PORT = '5309'
GEOIP_DEFAULT_VAL = 'us'
GEOIP_DEFAULT_TIMEOUT = .2

# A smaller range of languages for the Marketplace.
AMO_LANGUAGES = ('en-US', 'es', 'pt-BR')
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])

# Not shown on the site, but .po files exist and these are available on the
# L10n dashboard.  Generally languages start here and move into AMO_LANGUAGES.
# This list also enables translation edits.
HIDDEN_LANGUAGES = (
    # List of languages from AMO's settings (excluding mkt's active locales).
    'af', 'ar', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'eu', 'fa',
    'fi', 'fr', 'ga-IE', 'he', 'hu', 'id', 'it', 'ja', 'ko', 'mn', 'nl', 'pl',
    'pt-PT', 'ro', 'ru', 'sk', 'sl', 'sq', 'sv-SE', 'uk', 'vi',
    'zh-CN', 'zh-TW',
    # The hidden list from AMO's settings:
    'cy', 'sr', 'sr-Latn', 'tr',
)

# Update this each time there's a major update.
DEV_AGREEMENT_LAST_UPDATED = datetime.date(2012, 2, 23)

# This is the iss (issuer) for app purchase JWTs.
# It must match that of the pay server that processes nav.mozPay().
# In webpay this is the ISSUER setting.
APP_PURCHASE_KEY = 'marketplace-dev.allizom.org'

# This is the shared secret key for signing app purchase JWTs.
# It must match that of the pay server that processes nav.mozPay().
# In webpay this is the SECRET setting.
APP_PURCHASE_SECRET = ''

# This is the aud (audience) for app purchase JWTs.
# It must match that of the pay server that processes nav.mozPay().
# In webpay this is the DOMAIN setting and on B2G this must match
# what's in the provider whitelist.
APP_PURCHASE_AUD = 'marketplace-dev.allizom.org'

# This is the typ for app purchase JWTs.
# It must match that of the pay server that processes nav.mozPay().
# On B2G this must match a provider in the whitelist.
APP_PURCHASE_TYP = 'mozilla/payments/pay/v1'
