import datetime
import os

from lib.settings_base import *
from mkt import asset_bundles
from mkt.constants import regions

# The origin URL for our Fireplace frontend, from which API requests come.
FIREPLACE_URL = ''

ALLOWED_HOSTS += ['.firefox.com', '.firefox.com.cn']
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

MKT_FEEDBACK_EMAIL = 'apps-feedback@mozilla.com'
MKT_REVIEWERS_EMAIL = 'app-reviewers@mozilla.org'
MKT_SENIOR_EDITORS_EMAIL = 'marketplace-staff+escalations@mozilla.org'
MKT_SUPPORT_EMAIL = 'app-reviewers@mozilla.org'
MARKETPLACE_EMAIL = 'marketplace-staff@mozilla.org'
ABUSE_EMAIL = 'Firefox Marketplace Staff <marketplace-staff+abuse@mozilla.org>'
NOBODY_EMAIL = 'Firefox Marketplace <nobody@mozilla.org>'
DEFAULT_FROM_EMAIL = 'Firefox Marketplace <nobody@mozilla.org>'

# Default app name for our webapp as specified in `manifest.webapp`.
WEBAPP_MANIFEST_NAME = 'Marketplace'

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
    'mkt.site',
    'mkt.account',
    'mkt.api',
    'mkt.collections',
    'mkt.comm',
    'mkt.commonplace',
    'mkt.detail',
    'mkt.developers',
    'mkt.ecosystem',
    'mkt.files',
    'mkt.lookup',
    'mkt.monolith',
    'mkt.purchase',
    'mkt.ratings',
    'mkt.receipts',
    'mkt.reviewers',
    'mkt.search',
    'mkt.stats',
    'mkt.submit',
    'mkt.zadmin',
    'mkt.webapps',
    'mkt.webpay',
)

# TODO: I want to get rid of these eventually but it breaks some junk now.
# MIDDLEWARE_CLASSES.remove('mobility.middleware.DetectMobileMiddleware')
# MIDDLEWARE_CLASSES.remove('mobility.middleware.XMobileMiddleware')
MIDDLEWARE_CLASSES = list(MIDDLEWARE_CLASSES)
MIDDLEWARE_CLASSES.append('mkt.site.middleware.RequestCookiesMiddleware')
MIDDLEWARE_CLASSES.append('mkt.carriers.middleware.CarrierURLMiddleware')
MIDDLEWARE_CLASSES.remove('amo.middleware.LocaleAndAppURLMiddleware')
MIDDLEWARE_CLASSES.remove('commonware.middleware.FrameOptionsHeader')
MIDDLEWARE_CLASSES.remove(
    'django_statsd.middleware.GraphiteRequestTimingMiddleware')
MIDDLEWARE_CLASSES.remove('multidb.middleware.PinningRouterMiddleware')

MIDDLEWARE_CLASSES += [
    'mkt.site.middleware.RestrictJSONUploadSizeMiddleware',
    'mkt.site.middleware.RedirectPrefixedURIMiddleware',
    'mkt.site.middleware.LocaleMiddleware',

    'mkt.regions.middleware.RegionMiddleware',
    'mkt.site.middleware.DeviceDetectionMiddleware',
    'mkt.api.middleware.TimingMiddleware',
    'mkt.api.middleware.APIVersionMiddleware',
    'mkt.api.middleware.CORSMiddleware',
    'mkt.api.middleware.APIPinningMiddleware',
    'mkt.api.middleware.APITransactionMiddleware',
    'mkt.api.middleware.APIFilterMiddleware'
]

TEMPLATE_DIRS += (path('mkt/templates'), path('mkt/zadmin/templates'))
TEMPLATE_CONTEXT_PROCESSORS = list(TEMPLATE_CONTEXT_PROCESSORS)
TEMPLATE_CONTEXT_PROCESSORS.remove('amo.context_processors.global_settings')
TEMPLATE_CONTEXT_PROCESSORS.remove('amo.context_processors.app')
TEMPLATE_CONTEXT_PROCESSORS += [
    'mkt.site.context_processors.global_settings',
    'mkt.carriers.context_processors.carrier_data',
]

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

# Path to store webpay product icons.
PRODUCT_ICON_PATH = NETAPP_STORAGE + '/product-icons'

# Base URL where webpay product icons are served from.
PRODUCT_ICON_URL = MEDIA_URL + '/product-icons'

# Number of days the webpay product icon is valid for.
# After this period, the icon will be re-fetched from its external URL.
# If you change this value, update the docs:
# https://developer.mozilla.org/en-US/docs/Web/Apps/Publishing/In-app_payments
PRODUCT_ICON_EXPIRY = 1

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
GEOIP_URL = ''
GEOIP_DEFAULT_VAL = 'worldwide'
GEOIP_DEFAULT_TIMEOUT = .2

SENTRY_DSN = None

# A smaller range of languages for the Marketplace.
AMO_LANGUAGES = (
    'ca', 'cs', 'de', 'el', 'en-US', 'es', 'fr', 'hr', 'hu', 'it', 'nl', 'pl',
    'pt-BR', 'ro', 'ru', 'sr', 'sr-Latn', 'sk', 'tr',
)
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])

# Not shown on the site, but .po files exist and these are available on the
# L10n dashboard.  Generally languages start here and move into AMO_LANGUAGES.
# This list also enables translation edits.
HIDDEN_LANGUAGES = (
    # List of languages from AMO's settings (excluding mkt's active locales).
    'af', 'ar', 'bg', 'da', 'eu', 'fa', 'fi', 'ga-IE', 'he', 'id', 'ja', 'ko',
    'mn', 'pt-PT', 'sl', 'sq', 'sv-SE', 'uk', 'vi', 'zh-CN', 'zh-TW',
    # The hidden list from AMO's settings:
    'cy',
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

# This is the typ for signature checking JWTs.
# This is used to integrate with WebPay.
SIG_CHECK_TYP = 'mozilla/payments/sigcheck/v1'

# This is the base filename of the `.zip` containing the packaged app for the
# consumer-facing pages of the Marketplace (aka Fireplace). Expected path:
#     /media/packaged-apps/<path>
MARKETPLACE_GUID = 'e6a59937-29e4-456a-b636-b69afa8693b4'

# A solitude specific settings that allows you to send fake refunds to
# solitude. The matching setting will have to be on in solitude, otherwise
# it will just laugh at your request.
BANGO_FAKE_REFUNDS = False

REST_FRAMEWORK = {
    'DEFAULT_MODEL_SERIALIZER_CLASS':
        'rest_framework.serializers.HyperlinkedModelSerializer',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'mkt.api.authentication.RestOAuthAuthentication',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'mkt.api.renderers.SuccinctJSONRenderer',
    ),
    'DEFAULT_PARSER_CLASSES': (
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.FormParser',
        'rest_framework.parsers.MultiPartParser',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        # By default no-one gets anything. You will have to override this
        # in each resource to match your needs.
        'mkt.api.authorization.AllowNone',
    ),
    'DEFAULT_PAGINATION_SERIALIZER_CLASS':
        'mkt.api.paginator.CustomPaginationSerializer',
    'DEFAULT_FILTER_BACKENDS': (
        'rest_framework.filters.DjangoFilterBackend',
    ),
    'PAGINATE_BY': 25,
    'PAGINATE_BY_PARAM': 'limit'
}

# Tastypie config to match Django Rest Framework.
API_LIMIT_PER_PAGE = 25

# Upon signing out (of Developer Hub/Reviewer Tools), redirect users to
# Developer Hub instead of to Fireplace.
LOGOUT_REDIRECT_URL = '/developers/'

# Name of our Commonplace repositories on GitHub.
COMMONPLACE_REPOS = ['commbadge', 'fireplace', 'marketplace-stats',
                     'rocketfuel']

# Limit payments to only people who are in a whitelist. This is useful for
# dev and stage server where only developers and testers should be able to make
# payments and not the general public.
#
# If you set this to True, then you will need to give people the waffle flag:
#   override-app-purchase
# For them to be able purchase apps.
PURCHASE_LIMITED = False
