import os

from lib.settings_base import *
from mkt import asset_bundles


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

# NOTE: If you want to disable this, you have to do it in this file right here
# since we do a lot of conditional stuff below.
REGION_STORES = False

# Support carrier URLs that prefix all other URLs, such as /telefonica/.
# NOTE: To set this to False, you need to do so in this file or copy over
# the conditional middleware removal below.
USE_CARRIER_URLS = True

# List of URL prefixes that will be interpretted as custom carrier stores.
# When a URL is prefixed with one of these values, the value will be
# available in mkt.carriers.get_carrier() and will be hidden from all other
# url resolvers.
CARRIER_URLS = ['telefonica']

MKT_REVIEWERS_EMAIL = 'app-reviews@mozilla.org'
MKT_SENIOR_EDITORS_EMAIL = 'amo-admin-reviews@mozilla.org'
MKT_SUPPORT_EMAIL = 'marketplace-developer-support@mozilla.org'
MARKETPLACE_EMAIL = 'amo-marketplace@mozilla.org'
ABUSE_EMAIL = 'Mozilla Marketplace <marketplace-abuse@mozilla.org>'
NOBODY_EMAIL = 'Mozilla Marketplace <nobody@mozilla.org>'
DEFAULT_FROM_EMAIL = 'Mozilla Marketplace <nobody@mozilla.org>'

# Default app name for our webapp as specified in `manifest.webapp`.
WEBAPP_MANIFEST_NAME = 'Mozilla Marketplace'

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
    'mkt.browse',
    'mkt.detail',
    'mkt.developers',
    'mkt.ecosystem',
    'mkt.home',
    'mkt.inapp_pay',
    'mkt.lookup',
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
)

if not REGION_STORES:
    SUPPORTED_NONLOCALES += (
        'manifest.webapp',
        'mozmarket.js',
        'appcache',
        'csrf',
    )

# TODO: I want to get rid of these eventually but it breaks some junk now.
# MIDDLEWARE_CLASSES.remove('mobility.middleware.DetectMobileMiddleware')
# MIDDLEWARE_CLASSES.remove('mobility.middleware.XMobileMiddleware')
# MIDDLEWARE_CLASSES.remove('cake.middleware.CookieCleaningMiddleware')
MIDDLEWARE_CLASSES = list(MIDDLEWARE_CLASSES)
if USE_CARRIER_URLS:
    MIDDLEWARE_CLASSES.insert(0,
        # This needs to come before CommonMiddleware so that APPEND_SLASH
        # is handled.
        'mkt.carriers.middleware.CarrierURLMiddleware',
    )
if REGION_STORES:
    MIDDLEWARE_CLASSES.remove('amo.middleware.LocaleAndAppURLMiddleware')
    MIDDLEWARE_CLASSES += [
        'mkt.site.middleware.RequestCookiesMiddleware',
        'mkt.site.middleware.RedirectPrefixedURIMiddleware',
        'mkt.site.middleware.LocaleMiddleware',
        'mkt.site.middleware.RegionMiddleware',
    ]
MIDDLEWARE_CLASSES += [
    'mkt.site.middleware.VaryOnAJAXMiddleware',

    # TODO: Remove this when we remove `request.can_view_consumer`.
    'amo.middleware.DefaultConsumerMiddleware',

    # Put this in your settings_local_mkt if you want the walled garden.
    #'amo.middleware.NoConsumerMiddleware',
    #'amo.middleware.LoginRequiredMiddleware',
]

TEMPLATE_DIRS += (path('mkt/templates'), path('mkt/zadmin/templates'))
TEMPLATE_CONTEXT_PROCESSORS = list(TEMPLATE_CONTEXT_PROCESSORS)
TEMPLATE_CONTEXT_PROCESSORS.remove('amo.context_processors.global_settings')
if REGION_STORES:
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

# Next level, no consumer for you!
NO_CONSUMER_MODULES = (
    'api',
    'bandwagon.views',
    'browse.views',
    'compat.views',
    'discovery.views',
    'files.views',
    'market.views',
    'piston',
    'users.views.edit',
    'users.views.purchases',
    'users.views.payments',
    'sharing.views',
    'tags.views',
    'versions.views',
    'mkt.account.views',
    'mkt.browse.views',
    'mkt.detail.views',
    'mkt.ratings.views',
    'mkt.payments.views',
    'mkt.stats.views',
    'mkt.support.views',
    'mkt.search.views',
    'mkt.webapps.views',
)

# Specific view modules and methods that we don't want to force login on.
NO_LOGIN_REQUIRED_MODULES = (
    'csp.views.policy',
    'csp.views.report',
    'mkt.developers',
    'mkt.lookup',
    'mkt.reviewers',
    'mkt.submit',
    'django_appcache.views.manifest',
    'django.views.i18n.javascript_catalog',
    'django.contrib.auth.views.password_reset',
    'django.contrib.auth.views.password_reset_done',
    'jingo.views.direct_to_template',
    'zadmin.views',
    'users.browserid_login',
    'mkt.ecosystem.views',
    'mkt.site.views',
    'mkt.zadmin.views',
    # in-app views have their own login protection.
    'mkt.inapp_pay.views',
    'tastypie.resources.wrapper',
)

# Extend the bundles.
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

# Link to the appcache manifest (activate it) when True.
USE_APPCACHE = False

# These are absolute paths to add to the cache. Wildcards are not allowed here.
# These paths will be added as-is to the cache section.
APPCACHE_TO_CACHE = [
    '/favicon.ico',
    'https://browserid.org/include.js'
]

APPCACHE_NET_PATHS = [
    '*'
]

# These are paths relative to MEDIA_ROOT that you want to explicitly
# cache. The browser will load *all* of these URLs when your app first loads
# so be mindful to only list essential media files. The actual URL of the path
# to cache will be determined using MEDIA_URL.
# If you use wildcards here the real paths to the file(s) will be
# expanded using glob.glob()

APPCACHE_MEDIA_TO_CACHE = [
    'js/mkt/consumer-min.js',
    'css/mkt/consumer-min.css'
]

APPCACHE_MEDIA_DEBUG = []
for f in list(asset_bundles.CSS['mkt/consumer']):
    if f.endswith('.less'):
        APPCACHE_MEDIA_DEBUG.append(f + '.css')
    else:
        APPCACHE_MEDIA_DEBUG.append(f)
APPCACHE_MEDIA_DEBUG.extend(asset_bundles.JS['mkt/consumer'])

# Are you working locally? place the following line in your settings_local:
# APPCACHE_MEDIA_TO_CACHE = APPCACHE_MEDIA_DEBUG

# Allowed `installs_allowed_from` values for manifest validator.
VALIDATOR_IAF_URLS = ['https://marketplace.mozilla.org']

# All JS vendor libraries in this list will be excluded from mozmarket.js.
# For example, if receiptverifier is broken and you need to disable it, add
# 'receiptverifier' to the list. See also mkt/site/views.py.
MOZMARKET_VENDOR_EXCLUDE = []

# When True, mozmarket.js will be served as minified JavaScript.
MINIFY_MOZMARKET = True
