# Django settings for addons-server project.

import logging
import os
import socket
from datetime import datetime

from django.utils.functional import lazy

import environ
import sentry_sdk
from corsheaders.defaults import default_headers
from kombu import Queue
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger

import olympia.core.logger
import olympia.core.sentry
from olympia.core.utils import get_version_json


env = environ.Env()

ENVIRON_SETTINGS_FILE_PATH = '/etc/olympia/settings.env'

if os.path.exists(ENVIRON_SETTINGS_FILE_PATH):
    env.read_env(env_file=ENVIRON_SETTINGS_FILE_PATH)


ALLOWED_HOSTS = [
    '.allizom.org',
    '.amo.nonprod.webservices.mozgcp.net',
    '.amo.prod.webservices.mozgcp.net',
    '.mozilla.org',
    '.mozilla.com',
    '.mozilla.net',
    '.mozaws.net',
]


# This variable should only be set to `True` for local env and internal hosts.
INTERNAL_ROUTES_ALLOWED = env('INTERNAL_ROUTES_ALLOWED', default=False)

if os.environ.get('ADDONS_SERVER_COMPONENT') == 'amo-internal-web':
    # Allow (much) higher number of fields to be submitted to internal web, it
    # serves the admin which can potentially have huge forms for the blocklist.
    DATA_UPLOAD_MAX_NUMBER_FIELDS = 100000

try:
    # If we have a build id (it should be generated when building the image),
    # we'll grab it here and add it to our CACHE_KEY_PREFIX. This will let us
    # not have to flush memcache during updates and it will let us preload
    # data into it before a production push.
    from build import BUILD_ID
except ImportError:
    BUILD_ID = ''

# Make filepaths relative to the root of olympia.
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ROOT = os.path.join(BASE_DIR, '..', '..')


def path(*folders):
    return os.path.join(ROOT, *folders)


DEBUG = env('DEBUG', default=False)

# Target is the target the current container image was built for.
TARGET = get_version_json().get('target')

DEV_MODE = False

# Host info that is hard coded for production images.
HOST_UID = None

# Used to determine if django should serve static files.
# For local deployments we want nginx to proxy static file requests to the
# uwsgi server and not try to serve them locally.
# In production, nginx serves these files from a CDN.
SERVE_STATIC_FILES = False

DEBUG_TOOLBAR_CONFIG = {
    # Deactivate django debug toolbar by default.
    'SHOW_TOOLBAR_CALLBACK': lambda request: DEBUG,
}

# Ensure that exceptions aren't re-raised.
DEBUG_PROPAGATE_EXCEPTIONS = False
SILENCED_SYSTEM_CHECKS = (
    # Recommendation to use OneToOneField instead of ForeignKey(unique=True)
    # but our translations are the way they are...
    'fields.W342',
    'django_recaptcha.recaptcha_test_key_error',
)

# rsvg-convert is used to save our svg static theme previews to png
RSVG_CONVERT_BIN = env('RSVG_CONVERT_BIN', default='rsvg-convert')

# Path to pngcrush (to optimize the PNGs uploaded by developers).
PNGCRUSH_BIN = env('PNGCRUSH_BIN', default='pngcrush')

# Path to our addons-linter binary
ADDONS_LINTER_BIN = env(
    'ADDONS_LINTER_BIN', default=path('node_modules/addons-linter/bin/addons-linter')
)
# --enable-background-service-worker linter flag value
ADDONS_LINTER_ENABLE_SERVICE_WORKER = False

DELETION_EMAIL = 'amo-notifications+deletion@mozilla.com'

DRF_API_VERSIONS = ['auth', 'v3', 'v4', 'v5']
DRF_API_REGEX = r'^/?api/(?:auth|v3|v4|v5)/'

DRF_API_NOT_SWAGGER_REGEX = rf'{DRF_API_REGEX}(?!swagger|redoc).*$'

# Add Access-Control-Allow-Origin: * header for the new API with
# django-cors-headers.
CORS_ALLOW_ALL_ORIGINS = True
# Exclude the `accounts/session` endpoint, see:
# https://github.com/mozilla/addons-server/issues/11100
CORS_URLS_REGEX = rf'{DRF_API_REGEX}(?!accounts/session/)'
# https://github.com/mozilla/addons-server/issues/17364
CORS_ALLOW_HEADERS = list(default_headers) + [
    'x-country-code',
]

DB_ENGINE = 'olympia.core.db.mysql'
DB_CHARSET = 'utf8mb4'


def get_db_config(environ_var, atomic_requests=True):
    values = env.db(var=environ_var, default='mysql://root:@127.0.0.1/olympia')

    values.update(
        {
            # Run all views in a transaction unless they are decorated not to.
            # `atomic_requests` should be `False` for database replicas where no
            # write operations will ever happen.
            'ATOMIC_REQUESTS': atomic_requests,
            # Pool our database connections up for 300 seconds
            'CONN_MAX_AGE': 300,
            'ENGINE': DB_ENGINE,
            'OPTIONS': {
                'charset': DB_CHARSET,
                'sql_mode': 'STRICT_ALL_TABLES',
                'isolation_level': 'read committed',
            },
            'TEST': {'CHARSET': 'utf8mb4', 'COLLATION': 'utf8mb4_general_ci'},
        }
    )

    return values


DATABASES = {
    'default': get_db_config('DATABASES_DEFAULT_URL'),
}

DATABASE_ROUTERS = ('multidb.PinningReplicaRouter',)

# Put the aliases for your slave databases in this list.
REPLICA_DATABASES = []

LOCAL_ADMIN_EMAIL = 'local_admin@mozilla.com'
LOCAL_ADMIN_USERNAME = 'local_admin'

DJANGO_EXTENSIONS_RESET_DB_MYSQL_ENGINES = [DB_ENGINE]

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# If running in a Windows environment this must be set to the same as your
# system time zone.
TIME_ZONE = 'UTC'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-US'

# Accepted locales / languages.
from olympia.core.languages import ALL_LANGUAGES, AMO_LANGUAGES  # noqa

# Bidirectional languages.
LANGUAGES_BIDI = ('ar', 'fa', 'he', 'ur')

# Explicit conversion of a shorter language code into a more specific one.
SHORTER_LANGUAGES = {
    'en': 'en-US',
    'es': 'es-ES',
    'ga': 'ga-IE',
    'pt': 'pt-PT',
    'sv': 'sv-SE',
    'zh': 'zh-CN',
}


def get_django_languages():
    from django.conf import settings

    return [
        (lang.lower(), names['native'])
        for lang, names in ALL_LANGUAGES.items()
        if lang in settings.AMO_LANGUAGES
    ]


# Override Django's built-in with our native names
# lazy because we can override AMO_LANGUAGES
LANGUAGES = lazy(get_django_languages, list)()


def get_language_url_map():
    from django.conf import settings

    return {locale.lower(): locale for locale in settings.AMO_LANGUAGES}


# lazy because we can override AMO_LANGUAGES
LANGUAGE_URL_MAP = lazy(get_language_url_map, dict)()

LOCALE_PATHS = (path('locale'),)

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# This enables localized formatting of numbers and dates/times. Deprecated in Django4.1
USE_L10N = True

# The host currently running the site.  Only use this in code for good reason;
# the site is designed to run on a cluster and should continue to support that
HOSTNAME = socket.gethostname()

# The front end domain of the site. If you're not running on a cluster this
# might be the same as HOSTNAME but don't depend on that.  Use this when you
# need the real domain.
DOMAIN = HOSTNAME

# The port used by the frontend when running frontend locally with
# addons-server in docker. This will default it to None for dev/prod/stage.
ADDONS_FRONTEND_PROXY_PORT = None

# Full base URL for your main site including protocol.  No trailing slash.
#   Example: https://addons.mozilla.org
SITE_URL = 'http://%s' % DOMAIN

# The base URL for the external user-facing frontend.  Only really useful for
# the internal admin instances of addons-server that don't run addons-frontend.
EXTERNAL_SITE_URL = env('EXTERNAL_SITE_URL', default=SITE_URL)

# Domain of the services site.  This is where your API, and in-product pages
# live.
SERVICES_DOMAIN = 'services.%s' % DOMAIN

# Full URL to your API service. No trailing slash.
#   Example: https://services.addons.mozilla.org
SERVICES_URL = 'http://%s' % SERVICES_DOMAIN

# Static and media URL for prod are hardcoded here to allow them to be set in
# the base CSP shared by all envs.
PROD_STATIC_URL = 'https://addons.mozilla.org/static-server/'
PROD_MEDIA_URL = 'https://addons.mozilla.org/user-media/'

# Static
STATIC_ROOT = path('site-static')
# Allow overriding static/media url path prefix
STATIC_URL_PREFIX = env('STATIC_URL_PREFIX')
MEDIA_URL_PREFIX = env('MEDIA_URL_PREFIX')
# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = MEDIA_URL_PREFIX
# URL that handles the static files served from STATIC_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/static/"
STATIC_URL = STATIC_URL_PREFIX

# Filter IP addresses of allowed clients that can post email through the API.
ALLOWED_CLIENTS_EMAIL_API = env.list('ALLOWED_CLIENTS_EMAIL_API', default=[])
# Auth token required to authorize inbound email.
INBOUND_EMAIL_SECRET_KEY = env('INBOUND_EMAIL_SECRET_KEY', default='')
# Validation key we need to send in POST response.
INBOUND_EMAIL_VALIDATION_KEY = env('INBOUND_EMAIL_VALIDATION_KEY', default='')
# Domain emails should be sent to.
INBOUND_EMAIL_DOMAIN = env('INBOUND_EMAIL_DOMAIN', default=DOMAIN)

# Tarballs in DUMPED_APPS_PATH deleted 30 days after they have been written.
DUMPED_APPS_DAYS_DELETE = 3600 * 24 * 30

# Tarballs in DUMPED_USERS_PATH deleted 30 days after they have been written.
DUMPED_USERS_DAYS_DELETE = 3600 * 24 * 30

# path that isn't just one /, and doesn't require any locale or app.
SUPPORTED_NONAPPS_NONLOCALES_REGEX = DRF_API_REGEX

# paths that don't require an app prefix
# This needs to be kept in sync with addons-frontend's
# validClientAppUrlExceptions
# https://github.com/mozilla/addons-frontend/blob/master/config/default-amo.js
SUPPORTED_NONAPPS = (
    'about',
    'abuse',
    'admin',
    'apps',
    'activity',
    'contribute.json',
    'developer_agreement',
    'developers',
    'editors',
    'review_guide',
    'google1f3e37b7351799a5.html',
    'google231a41e803e464e9.html',
    'reviewers',
    'robots.txt',
    'statistics',
    'services',
    'sitemap.xml',
    STATIC_URL_PREFIX.strip('/'),
    'update',
    MEDIA_URL_PREFIX.strip('/'),
    '__heartbeat__',
    '__lbheartbeat__',
    '__version__',
)
DEFAULT_APP = 'firefox'

# paths that don't require a locale prefix
# This needs to be kept in sync with addons-frontend's validLocaleUrlExceptions
# https://github.com/mozilla/addons-frontend/blob/master/config/default-amo.js
SUPPORTED_NONLOCALES = (
    'activity',
    'contribute.json',
    'google1f3e37b7351799a5.html',
    'google231a41e803e464e9.html',
    'robots.txt',
    'services',
    'sitemap.xml',
    'downloads',
    STATIC_URL_PREFIX.strip('/'),
    'update',
    MEDIA_URL_PREFIX.strip('/'),
    '__heartbeat__',
    '__lbheartbeat__',
    '__version__',
)

# Make this unique, and don't share it with anybody.
SECRET_KEY = env(
    'SECRET_KEY', default='this-is-a-dummy-key-and-its-overridden-for-prod-servers'
)

# This is a unique key shared between us and the CDN to prove that a request
# came from the CDN. It will be passed as a HTTP_X_REQUEST_VIA_CDN header to
# all requests from the CDN
SECRET_CDN_TOKEN = env('SECRET_CDN_TOKEN', default=None)

# Templates configuration.
# List of path patterns for which we should be using Django Template Language.
# If you add things here, don't forget to also change babel.cfg !
JINJA_EXCLUDE_TEMPLATE_PATHS = (
    # All emails should be processed with Django for consistency.
    r'^.*\/emails\/',
    # ^admin\/ covers most django admin templates, since their path should
    # follow /admin/<app>/<model>/*
    r'^admin\/',
    # This is a django form widget template.
    r'^devhub/forms/widgets/compat_app_input_option.html',
    # Third-party apps + django.
    r'debug_toolbar',
    r'^rangefilter\/',
    r'^registration\/',
    # Django's sitemap_index.xml template uses some syntax that jinja doesn't support
    r'sitemap_index.xml',
    # Swagger URLs are for the API docs, use some syntax that jinja doesn't support
    r'drf_spectacular/swagger_ui.html',
    r'drf_spectacular/redoc.html',
    r'drf_spectacular/swagger_ui.js',
    r'django_extensions/graph_models/django2018/digraph.dot',
    r'django_extensions/graph_models/django2018/label.dot',
    r'django_extensions/graph_models/django2018/relation.dot',
    r'django_jsonform\/',
)

TEMPLATES = [
    {
        'BACKEND': 'django_jinja.backend.Jinja2',
        # This is used by olympia.core.babel to find the template configuration
        # for jinja2 templates.
        'NAME': 'jinja2',
        'APP_DIRS': True,
        'DIRS': (
            path('media', 'docs'),
            path('src/olympia/templates'),
        ),
        'OPTIONS': {
            'globals': {
                'vite_hmr_client': (
                    'django_vite.templatetags.django_vite.vite_hmr_client'
                ),
            },
            # http://jinja.pocoo.org/docs/dev/extensions/#newstyle-gettext
            'newstyle_gettext': True,
            # Match our regular .html and .txt file endings except
            # for the admin and a handful of other paths
            'match_extension': None,
            'match_regex': r'^(?!({paths})).*'.format(
                paths='|'.join(JINJA_EXCLUDE_TEMPLATE_PATHS)
            ),
            'context_processors': (
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.debug',
                'django.template.context_processors.media',
                'django.template.context_processors.request',
                'django.contrib.messages.context_processors.messages',
                'olympia.amo.context_processors.i18n',
                'olympia.amo.context_processors.global_settings',
            ),
            'extensions': (
                'jinja2.ext.do',
                'jinja2.ext.i18n',
                'jinja2.ext.loopcontrols',
                'django_jinja.builtins.extensions.CsrfExtension',
                'django_jinja.builtins.extensions.DjangoFiltersExtension',
                'django_jinja.builtins.extensions.StaticFilesExtension',
                'django_jinja.builtins.extensions.TimezoneExtension',
                'django_jinja.builtins.extensions.UrlsExtension',
                'olympia.amo.templatetags.jinja_helpers.Spaceless',
                'waffle.jinja.WaffleExtension',
            ),
            'policies': {
                'ext.i18n.trimmed': True,
            },
            'finalize': lambda x: x if x is not None else '',
            'translation_engine': 'django.utils.translation',
            'autoescape': True,
            'trim_blocks': True,
        },
    },
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': (
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.debug',
                'django.template.context_processors.media',
                'django.template.context_processors.request',
                'django.contrib.messages.context_processors.messages',
            ),
        },
    },
]

X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000

# Prefer using `X-Forwarded-Port` header instead of `Port` header.
# We are behind both, the ELB and nginx which forwards requests to our
# uwsgi app.
# Our current request flow is this:
# Request -> ELB (terminates SSL) -> Nginx -> Uwsgi -> addons-server
#
# The ELB terminates SSL and properly sets `X-Forwarded-Port` header
# as well as `X-Forwarded-Proto` and others.
# Nginx on the other hand runs on port 81 and thus sets `Port` to be
# 81 but to make CSRF detection and other mechanisms work properly
# we need to know that we're running on either port 80 or 443, or do something
# with SECURE_PROXY_SSL_HEADER but we shouldn't if we can avoid that.
# So, let's simply grab the properly set `X-Forwarded-Port` header.
# https://github.com/mozilla/addons-server/issues/8835#issuecomment-405340432
#
# This is also backwards compatible for our local setup since Django falls back
# to using `Port` if `X-Forwarded-Port` isn't set.
USE_X_FORWARDED_PORT = True

MIDDLEWARE = (
    # Our middleware to make safe requests non-atomic needs to be at the top.
    'olympia.amo.middleware.NonAtomicRequestsForSafeHttpMethodsMiddleware',
    # Test if it's an API request first so later middlewares don't need to.
    # Also add relevant Vary header to API responses.
    'olympia.api.middleware.APIRequestMiddleware',
    'olympia.amo.middleware.CacheControlMiddleware',
    # Gzip middleware needs to be executed after every modification to the
    # response, so it's placed at the top of the list.
    'django.middleware.gzip.GZipMiddleware',
    # Statsd and logging come first to get timings etc. Munging REMOTE_ADDR
    # must come before middlewares potentially using REMOTE_ADDR, so it's
    # also up there.
    'olympia.amo.middleware.GraphiteRequestTimingMiddleware',
    # GraphiteMiddlewareNoAuth is a custom GraphiteMiddleware that doesn't
    # handle response.auth, to avoid evaluating request.user.
    'olympia.amo.middleware.GraphiteMiddlewareNoAuth',
    'olympia.amo.middleware.SetRemoteAddrFromForwardedFor',
    # AMO URL middleware is as high as possible to get locale/app aware URLs.
    'olympia.amo.middleware.LocaleAndAppURLMiddleware',
    'olympia.amo.middleware.RemoveSlashMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'multidb.middleware.PinningRouterMiddleware',
    'waffle.middleware.WaffleMiddleware',
    # CSP and CORS need to come before CommonMiddleware because they might
    # need to add headers to 304 responses returned by CommonMiddleware.
    'olympia.amo.middleware.CSPMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    # Enable conditional processing, e.g ETags.
    'django.middleware.http.ConditionalGetMiddleware',
    'olympia.amo.middleware.NoVarySessionMiddleware',
    'olympia.amo.middleware.LBHeartbeatMiddleware',
    'olympia.amo.middleware.CommonMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'olympia.amo.middleware.AuthenticationMiddlewareWithoutAPI',
    # Our middleware that adds additional information for the user
    # and API about our read-only status.
    'olympia.amo.middleware.ReadOnlyMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    # This should come after AuthenticationMiddlewareWithoutAPI (to get the
    # current user) and after SetRemoteAddrFromForwardedFor (to get the correct
    # IP).
    'olympia.access.middleware.UserAndAddrMiddleware',
    'olympia.amo.middleware.RequestIdMiddleware',
    'olympia.amo.middleware.TokenValidMiddleware',
)

# Auth
AUTH_USER_MODEL = 'users.UserProfile'

# Override this in the site settings.
ROOT_URLCONF = 'olympia.urls'

INSTALLED_APPS = (
    # The translations app *must* be the very first. This isn't necessarily
    # relevant for daily business but very important for running initial
    # migrations during our tests and local setup.
    # Foreign keys to the `translations` table point to `id` which isn't
    # unique on it's own but has a (id, locale) unique_together index.
    # If `translations` would come after `olympia.addons` for example
    # Django tries to first, create the table translations, then create the
    # addons table, then adds the foreign key and only after that adds the
    # unique_together index to `translations`. MySQL needs that index to be
    # created first though, otherwise you'll run into
    # `ERROR 1215 (HY000): Cannot add foreign key constraint` errors.
    'olympia.translations',
    'olympia.core',
    'olympia.amo',  # amo comes first so it always takes precedence.
    'olympia.abuse',
    'olympia.access',
    'olympia.accounts',
    'olympia.activity',
    'olympia.addons',
    'olympia.api',
    'olympia.applications',
    'olympia.bandwagon',
    'olympia.blocklist',
    'olympia.browse',
    'olympia.devhub',
    'olympia.discovery',
    'olympia.files',
    'olympia.git',
    'olympia.hero',
    'olympia.lib.es',
    'olympia.lib.akismet',
    'olympia.pages',
    'olympia.promoted',
    'olympia.ratings',
    'olympia.reviewers',
    'olympia.scanners',
    'olympia.search',
    'olympia.shelves',
    'olympia.stats',
    'olympia.tags',
    'olympia.users',
    'olympia.versions',
    'olympia.yara',
    'olympia.zadmin',
    # Third party apps
    'csp',
    'aesfield',
    'django_extensions',
    'rest_framework',
    'waffle',
    'django_jinja',
    'rangefilter',
    'django_recaptcha',
    'drf_spectacular',
    'drf_spectacular_sidecar',
    'django_vite',
    # Django contrib apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.humanize',
    'django.contrib.messages',
    'django.contrib.sessions',
    'django.contrib.sitemaps',
    'django.contrib.staticfiles',
    # Has to load after auth
    'django_statsd',
    'django_jsonform',
)

# These need to point to prod, because that's where the database lives. You can
# change it locally to test the extraction process, but be careful not to
# accidentally nuke translations when doing that!
DISCOVERY_EDITORIAL_CONTENT_API = (
    'https://addons.mozilla.org/api/v4/discovery/editorial/'
)
PRIMARY_HERO_EDITORIAL_CONTENT_API = (
    'https://addons.mozilla.org/api/v4/hero/primary/?all=true&raw'
)
SECONDARY_HERO_EDITORIAL_CONTENT_API = (
    'https://addons.mozilla.org/api/v4/hero/secondary/?all=true'
)
HOMEPAGE_SHELVES_EDITORIAL_CONTENT_API = (
    'https://addons.mozilla.org/api/v5/shelves/editorial'
)

# Filename where the strings will be stored. Used in extract_content_strings
# management command, but note that the filename is hardcoded in babel.cfg.
EDITORIAL_CONTENT_FILENAME = 'src/olympia/discovery/strings.jinja2'

CACHES = {
    'default': env.cache(
        'CACHES_DEFAULT',
        'memcache://%s' % os.environ.get('MEMCACHE_LOCATION', 'localhost:11211'),
    )
}
CACHES['default']['TIMEOUT'] = 500
CACHES['default']['BACKEND'] = 'django.core.cache.backends.memcached.PyMemcacheCache'
# Prefix for cache keys (will prevent collisions when running parallel copies)
CACHES['default']['KEY_PREFIX'] = 'amo:%s:' % BUILD_ID

# Outgoing URL bouncer
REDIRECT_URL = env(
    'REDIRECT_URL', default='https://prod.outgoing.prod.webservices.mozgcp.net/v1/'
)
REDIRECT_SECRET_KEY = env('REDIRECT_SECRET_KEY', default='')

# Allow URLs from these servers. Use full domain names.
REDIRECT_URL_ALLOW_LIST = ['addons.mozilla.org']

SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
# See: https://github.com/mozilla/addons-server/issues/1789
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
# This value must be kept in sync with authTokenValidFor from addons-frontend:
# https://github.com/mozilla/addons-frontend/blob/2f480b474fe13a676237fe76a1b2a057e4a2aac7/config/default-amo.js#L111
SESSION_COOKIE_AGE = 2592000  # 30 days
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_DOMAIN = '.%s' % DOMAIN  # bug 608797
MESSAGE_STORAGE = 'django.contrib.messages.storage.cookie.CookieStorage'

WAFFLE_SECURE = True

# These should have app+locale at the start to avoid redirects
LOGIN_URL = '/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
# When logging in with browser ID, a username is created automatically.
# In the case of duplicates, the process is recursive up to this number
# of times.
MAX_GEN_USERNAME_TRIES = 50

# Email settings
ADDONS_EMAIL = 'nobody@mozilla.org'
DEFAULT_FROM_EMAIL = f'Mozilla Add-ons <{ADDONS_EMAIL}>'

# Email goes to the console by default.  s/console/smtp/ for regular delivery
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Please use all lowercase for the deny_list.
EMAIL_DENY_LIST = env.list('EMAIL_DENY_LIST', default=('nobody@mozilla.org',))

# URL for Add-on Validation FAQ.
VALIDATION_FAQ_URL = (
    'https://wiki.mozilla.org/Add-ons/Reviewers/Guide/'
    'AddonReviews#Step_2:_Automatic_validation'
)

SHIELD_STUDIES_SUPPORT_URL = 'https://support.mozilla.org/kb/shield'


# Celery
CELERY_BROKER_URL = env(
    'CELERY_BROKER_URL',
    default=os.environ.get(
        'CELERY_BROKER_URL', 'amqp://olympia:olympia@localhost:5672/olympia'
    ),
)
CELERY_BROKER_CONNECTION_TIMEOUT = 0.1
CELERY_BROKER_HEARTBEAT = 60 * 15
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_RESULT_BACKEND = env(
    'CELERY_RESULT_BACKEND',
    default=os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1'),
)

CELERY_TASK_IGNORE_RESULT = True
CELERY_SEND_TASK_ERROR_EMAILS = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
# Testing responsiveness without rate limits.
CELERY_WORKER_DISABLE_RATE_LIMITS = True

# Only serialize celery tasks using JSON.
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

# When testing, we always want tasks to raise exceptions. Good for sanity.
CELERY_TASK_EAGER_PROPAGATES = True

# Time in seconds before celery.exceptions.SoftTimeLimitExceeded is raised.
# The task can catch that and recover but should exit ASAP. Note that there is
# a separate, shorter timeout for validation tasks.
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 30

# List of modules that contain tasks and that wouldn't be autodiscovered by
# celery. Typically, it's either `tasks` modules from something not in
# INSTALLED_APPS, or modules not called `tasks`.
CELERY_IMPORTS = (
    'olympia.lib.crypto.tasks',
    'olympia.search.management.commands.reindex',
)

CELERY_TASK_QUEUES = (
    Queue('adhoc', routing_key='adhoc'),
    Queue('amo', routing_key='amo'),
    Queue('cron', routing_key='cron'),
    Queue('default', routing_key='default'),
    Queue('devhub', routing_key='devhub'),
    Queue('priority', routing_key='priority'),
    Queue('reviewers', routing_key='reviewers'),
    Queue('zadmin', routing_key='zadmin'),
)

# We have separate workers for processing some tasks without waiting for others
# Notes:
# - Always add routes here instead of @task(queue=<name>)
# - Make sure the queues exist by coordinating with cloudops-deployment repo.
CELERY_TASK_ROUTES = {
    # Priority.
    # If your tasks need to be run as soon as possible, add them here so they
    # are routed to the priority queue.
    'olympia.addons.tasks.index_addons': {'queue': 'priority'},
    'olympia.blocklist.tasks.process_blocklistsubmission': {'queue': 'priority'},
    'olympia.blocklist.tasks.upload_filter': {'queue': 'priority'},
    'olympia.versions.tasks.generate_static_theme_preview': {'queue': 'priority'},
    # Adhoc
    # A queue to be used for one-off tasks that could be resource intensive or
    # tasks we want completely separate from the rest.
    'olympia.addons.tasks.delete_erroneously_added_overgrowth_needshumanreview': {
        'queue': 'adhoc'
    },
    'olympia.addons.tasks.find_inconsistencies_between_es_and_db': {'queue': 'adhoc'},
    'olympia.search.management.commands.reindex.create_new_index': {'queue': 'adhoc'},
    'olympia.search.management.commands.reindex.delete_indexes': {'queue': 'adhoc'},
    'olympia.search.management.commands.reindex.flag_database': {'queue': 'adhoc'},
    'olympia.search.management.commands.reindex.unflag_database': {'queue': 'adhoc'},
    'olympia.search.management.commands.reindex.update_aliases': {'queue': 'adhoc'},
    'olympia.translations.tasks.strip_html_from_summaries': {'queue': 'adhoc'},
    'olympia.translations.tasks.update_outgoing_url': {'queue': 'adhoc'},
    'olympia.versions.tasks.delete_list_theme_previews': {'queue': 'adhoc'},
    'olympia.versions.tasks.hard_delete_versions': {'queue': 'adhoc'},
    'olympia.activity.tasks.create_ratinglog': {'queue': 'adhoc'},
    'olympia.files.tasks.extract_host_permissions': {'queue': 'adhoc'},
    'olympia.lib.crypto.tasks.bump_and_resign_addons': {'queue': 'adhoc'},
    'olympia.users.tasks.restrict_banned_users': {'queue': 'adhoc'},
    # Misc AMO tasks.
    'olympia.blocklist.tasks.monitor_remote_settings': {'queue': 'amo'},
    'olympia.abuse.tasks.appeal_to_cinder': {'queue': 'amo'},
    'olympia.abuse.tasks.handle_forward_to_legal_action': {'queue': 'amo'},
    'olympia.abuse.tasks.report_to_cinder': {'queue': 'amo'},
    'olympia.abuse.tasks.report_decision_to_cinder_and_notify': {'queue': 'amo'},
    'olympia.abuse.tasks.sync_cinder_policies': {'queue': 'amo'},
    'olympia.abuse.tasks.auto_resolve_job': {'queue': 'adhoc'},
    'olympia.accounts.tasks.clear_sessions_event': {'queue': 'amo'},
    'olympia.accounts.tasks.delete_user_event': {'queue': 'amo'},
    'olympia.accounts.tasks.primary_email_change_event': {'queue': 'amo'},
    'olympia.addons.tasks.delete_addons': {'queue': 'amo'},
    'olympia.addons.tasks.delete_all_addon_media_with_backup': {'queue': 'amo'},
    'olympia.addons.tasks.delete_preview_files': {'queue': 'amo'},
    'olympia.addons.tasks.disable_addons': {'queue': 'amo'},
    'olympia.addons.tasks.extract_colors_from_static_themes': {'queue': 'amo'},
    'olympia.addons.tasks.recreate_theme_previews': {'queue': 'amo'},
    'olympia.addons.tasks.resize_icon': {'queue': 'amo'},
    'olympia.addons.tasks.resize_preview': {'queue': 'amo'},
    'olympia.addons.tasks.restore_all_addon_media_from_backup': {'queue': 'amo'},
    'olympia.addons.tasks.version_changed': {'queue': 'amo'},
    'olympia.amo.tasks.delete_logs': {'queue': 'amo'},
    'olympia.amo.tasks.send_email': {'queue': 'amo'},
    'olympia.amo.tasks.set_modified_on_object': {'queue': 'amo'},
    'olympia.bandwagon.tasks.collection_meta': {'queue': 'amo'},
    'olympia.blocklist.tasks.cleanup_old_files': {'queue': 'amo'},
    'olympia.devhub.tasks.recreate_previews': {'queue': 'amo'},
    'olympia.ratings.tasks.addon_bayesian_rating': {'queue': 'amo'},
    'olympia.ratings.tasks.addon_rating_aggregates': {'queue': 'amo'},
    'olympia.ratings.tasks.update_denorm': {'queue': 'amo'},
    'olympia.tags.tasks.update_all_tag_stats': {'queue': 'amo'},
    'olympia.tags.tasks.update_tag_stat': {'queue': 'amo'},
    'olympia.users.tasks.delete_photo': {'queue': 'amo'},
    'olympia.users.tasks.resize_photo': {'queue': 'amo'},
    'olympia.users.tasks.update_user_ratings_task': {'queue': 'amo'},
    'olympia.versions.tasks.delete_preview_files': {'queue': 'amo'},
    'olympia.versions.tasks.duplicate_addon_version_for_rollback': {'queue': 'amo'},
    # 'Default' queue. In theory shouldn't be used, it's mostly a fallback.
    'celery.accumulate': {'queue': 'default'},
    'celery.backend_cleanup': {'queue': 'default'},
    'celery.chain': {'queue': 'default'},
    'celery.chord': {'queue': 'default'},
    'celery.chord_unlock': {'queue': 'default'},
    'celery.chunks': {'queue': 'default'},
    'celery.group': {'queue': 'default'},
    'celery.map': {'queue': 'default'},
    'celery.starmap': {'queue': 'default'},
    # Devhub & related.
    'olympia.activity.tasks.process_email': {'queue': 'devhub'},
    'olympia.devhub.tasks.check_data_collection_permissions': {'queue': 'devhub'},
    'olympia.devhub.tasks.check_for_api_keys_in_file': {'queue': 'devhub'},
    'olympia.devhub.tasks.create_initial_validation_results': {'queue': 'devhub'},
    'olympia.devhub.tasks.forward_linter_results': {'queue': 'devhub'},
    'olympia.devhub.tasks.get_preview_sizes': {'queue': 'devhub'},
    'olympia.devhub.tasks.handle_file_validation_result': {'queue': 'devhub'},
    'olympia.devhub.tasks.handle_upload_validation_result': {'queue': 'devhub'},
    'olympia.devhub.tasks.revoke_api_key': {'queue': 'devhub'},
    'olympia.devhub.tasks.send_initial_submission_acknowledgement_email': {
        'queue': 'devhub'
    },
    'olympia.devhub.tasks.submit_file': {'queue': 'devhub'},
    'olympia.devhub.tasks.validate_file': {'queue': 'devhub'},
    'olympia.devhub.tasks.validate_upload': {'queue': 'devhub'},
    'olympia.files.tasks.repack_fileupload': {'queue': 'devhub'},
    'olympia.scanners.tasks.call_webhooks_during_validation': {'queue': 'devhub'},
    'olympia.scanners.tasks.run_customs': {'queue': 'devhub'},
    'olympia.scanners.tasks.run_narc_on_version': {'queue': 'devhub'},
    'olympia.scanners.tasks.run_yara': {'queue': 'devhub'},
    'olympia.versions.tasks.call_webhooks_on_source_code_uploaded': {'queue': 'devhub'},
    'olympia.versions.tasks.soft_block_versions': {'queue': 'devhub'},
    # Crons.
    'olympia.addons.tasks.update_addon_average_daily_users': {'queue': 'cron'},
    'olympia.addons.tasks.update_addon_hotness': {'queue': 'cron'},
    'olympia.addons.tasks.update_addon_weekly_downloads': {'queue': 'cron'},
    'olympia.promoted.tasks.add_high_adu_extensions_to_notable': {'queue': 'cron'},
    'olympia.abuse.tasks.flag_high_abuse_reports_addons_according_to_review_tier': {
        'queue': 'cron'
    },
    'olympia.addons.tasks.flag_high_hotness_according_to_review_tier': {
        'queue': 'cron'
    },
    'olympia.ratings.tasks.flag_high_rating_addons_according_to_review_tier': {
        'queue': 'cron'
    },
    'olympia.users.tasks.sync_suppressed_emails_task': {'queue': 'cron'},
    'olympia.users.tasks.send_suppressed_email_confirmation': {'queue': 'devhub'},
    'olympia.users.tasks.bulk_add_disposable_email_domains': {'queue': 'devhub'},
    # Reviewers.
    'olympia.reviewers.tasks.recalculate_post_review_weight': {'queue': 'reviewers'},
    # Admin.
    'olympia.scanners.tasks.mark_scanner_query_rule_as_completed_or_aborted': {
        'queue': 'zadmin'
    },
    'olympia.scanners.tasks.run_scanner_query_rule': {'queue': 'zadmin'},
    'olympia.scanners.tasks.run_scanner_query_rule_on_versions_chunk': {
        'queue': 'zadmin'
    },
    'olympia.zadmin.tasks.celery_error': {'queue': 'zadmin'},
    'olympia.blocklist.tasks.upload_mlbf_to_remote_settings_task': {'queue': 'zadmin'},
}

# See PEP 391 for formatting help.
LOGGING = {
    'version': 1,
    'filters': {},
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': olympia.core.logger.AMOMozlogFormatter,
            'logger_name': 'http_app_addons',
        },
    },
    'handlers': {
        'mozlog': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
        'null': {
            'class': 'logging.NullHandler',
        },
        'statsd': {
            'level': 'ERROR',
            'class': 'django_statsd.loggers.errors.StatsdHandler',
        },
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {'handlers': ['mozlog'], 'level': logging.INFO},
    'loggers': {
        'amqp': {'handlers': ['null'], 'level': logging.WARNING, 'propagate': False},
        'babel': {'handlers': ['console'], 'level': logging.INFO, 'propagate': False},
        'blib2to3.pgen2.driver': {
            'handlers': ['null'],
            'level': logging.INFO,
            'propagate': False,
        },
        'caching': {'handlers': ['mozlog'], 'level': logging.ERROR, 'propagate': False},
        'caching.invalidation': {
            'handlers': ['null'],
            'level': logging.INFO,
            'propagate': False,
        },
        'celery.worker.strategy': {
            'handlers': ['mozlog'],
            'level': logging.WARNING,
            'propagate': False,
        },
        'django': {
            'handlers': ['statsd'],
            'level': logging.ERROR,
            'propagate': True,
        },
        # Django CSRF related warnings
        'django.security.csrf': {
            'handlers': ['mozlog'],
            'level': logging.WARNING,
            'propagate': True,
        },
        'elastic_transport.transport': {
            'handlers': ['null'],
            'level': logging.INFO,
            'propagate': False,
        },
        'filtercascade': {
            'handlers': ['mozlog'],
            # Ignore INFO or DEBUG from filtercascade, it logs too much.
            'level': logging.WARNING,
            'propagate': False,
        },
        'mohawk.util': {
            'handlers': ['mozlog'],
            # Ignore INFO or DEBUG from mohawk.util, it logs too much.
            'level': logging.WARNING,
            'propagate': False,
        },
        'parso': {'handlers': ['null'], 'level': logging.INFO, 'propagate': False},
        'sentry_sdk': {
            'handlers': ['mozlog'],
            'level': logging.WARNING,
            'propagate': False,
        },
        'request': {
            'handlers': ['mozlog'],
            'level': logging.WARNING,
            'propagate': False,
        },
        'z.celery': {
            'handlers': ['statsd'],
            'level': logging.ERROR,
            'propagate': True,
        },
        'z.pool': {'handlers': ['mozlog'], 'level': logging.ERROR, 'propagate': False},
    },
}

# CSP Settings
# https://github.com/mozilla/addons/issues/14799#issuecomment-2127359422
# These match Google's recommendations for CSP with GA4.
GOOGLE_TAGMANAGER_HOST = 'https://*.googletagmanager.com'
GOOGLE_ANALYTICS_HOST = 'https://*.google-analytics.com'
GOOGLE_ADDITIONAL_ANALYTICS_HOST = 'https://*.analytics.google.com'

RECAPTCHA_URL = 'https://www.recaptcha.net/recaptcha/'

CONTENT_SECURITY_POLICY = {
    'DIRECTIVES': {
        # NOTE: default-src MUST be set otherwise things not set
        # will default to being open to anything.
        'default-src': ("'none'",),
        'child-src': (RECAPTCHA_URL,),
        'connect-src': (
            "'self'",
            GOOGLE_ANALYTICS_HOST,
            GOOGLE_ADDITIONAL_ANALYTICS_HOST,
            GOOGLE_TAGMANAGER_HOST,
        ),
        'font-src': ("'self'", PROD_STATIC_URL),
        'form-action': ("'self'",),
        'frame-src': (RECAPTCHA_URL,),
        'img-src': (
            "'self'",
            'blob:',  # Needed for image uploads.
            'data:',  # Needed for theme wizard.
            PROD_STATIC_URL,
            PROD_MEDIA_URL,
            GOOGLE_ANALYTICS_HOST,
            GOOGLE_TAGMANAGER_HOST,
        ),
        'media-src': ('https://videos.cdn.mozilla.net',),
        'object-src': ("'none'",),
        'report-uri': '/__cspreport__',
        'script-src': (
            GOOGLE_ANALYTICS_HOST,
            GOOGLE_TAGMANAGER_HOST,
            RECAPTCHA_URL,
            'https://www.gstatic.com/recaptcha/',
            'https://www.gstatic.cn/recaptcha/',
            PROD_STATIC_URL,
        ),
        'style-src': ("'unsafe-inline'", PROD_STATIC_URL),
    },
    'EXCLUDE_URL_PREFIXES': (),
}

# Should robots.txt deny everything or disallow a calculated list of URLs we
# don't want to be crawled?  Default is true, allow everything, toggled to
# False on -dev and stage.
# Also see http://www.google.com/support/webmasters/bin/answer.py?answer=93710
ENGAGE_ROBOTS = True

# Read-only mode setup.
READ_ONLY = env.bool('READ_ONLY', default=False)


# Turn on read-only mode in local_settings.py by putting this line
# at the VERY BOTTOM: read_only_mode(globals())
def read_only_mode(env):
    env['READ_ONLY'] = True

    # Replace the default (master) db with a slave connection.
    if not env.get('REPLICA_DATABASES'):
        raise Exception('We need at least one slave database.')
    slave = env['REPLICA_DATABASES'][0]
    env['DATABASES']['default'] = env['DATABASES'][slave]

    # No sessions without the database, so disable auth.
    env['AUTHENTICATION_BACKENDS'] = ('olympia.users.backends.NoAuthForYou',)


# Uploaded file limits
MAX_IMAGE_UPLOAD_SIZE = 4 * 1024 * 1024
MAX_ICON_UPLOAD_SIZE = MAX_IMAGE_UPLOAD_SIZE
MAX_PHOTO_UPLOAD_SIZE = MAX_IMAGE_UPLOAD_SIZE
MAX_STATICTHEME_SIZE = 7 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_SIZE = 250 * 1024 * 1024
# Not a Django setting -- needs to be implemented by relevant forms
# See SourceForm, _submit_upload(), validate_review_attachment(), etc. Since it
# is displayed to users with filesizeformat it should be using powers of 1000
# to be displayed correctly.
MAX_UPLOAD_SIZE = 200 * 1000 * 1000

# File uploads should have -rw-r--r-- permissions in order to be served by
# nginx later one. The 0o prefix is intentional, this is an octal value.
FILE_UPLOAD_PERMISSIONS = 0o644

# RECAPTCHA: overload the following key settings in local_settings.py
# with your keys.
RECAPTCHA_PUBLIC_KEY = env('NOBOT_RECAPTCHA_PUBLIC_KEY', default='')
RECAPTCHA_PRIVATE_KEY = env('NOBOT_RECAPTCHA_PRIVATE_KEY', default='')
RECAPTCHA_DOMAIN = 'www.recaptcha.net'

# Send Django signals asynchronously on a background thread.
ASYNC_SIGNALS = True

# Number of seconds before celery tasks will abort addon validation:
VALIDATOR_TIMEOUT = 360

# Max number of warnings/errors to show from validator. Set to None for no
# limit.
VALIDATOR_MESSAGE_LIMIT = 500

# Feature flags
UNLINK_SITE_STATS = True

# See: https://www.nginx.com/resources/wiki/start/topics/examples/xsendfile/
XSENDFILE_HEADER = 'X-Accel-Redirect'

MOBILE_COOKIE = 'mamo'

# Path to `ps`.
PS_BIN = '/bin/ps'

# The maximum file size that you can have inside a zip file.
FILE_UNZIP_SIZE_LIMIT = 104857600

# How long to delay tasks relying on file system to cope with NFS lag.
NFS_LAG_DELAY = 3

# Elasticsearch
# The ES_HOST should be be any sort of valid URL, like:
# - host e.g. 'localhost'
# - host:port e.g. 'localhost:9200'
# - scheme://host:port e.g. 'https://localhost:9200'
# - scheme://user:password@host:port e.g. https://foo:bar@localhost:9200
# Fallback to the default used by CI.
ES_HOST = env('ELASTICSEARCH_LOCATION', default='127.0.0.1:9200')
ES_INDEXES = {
    'default': 'addons',
}
ES_TIMEOUT = 30
ES_DEFAULT_NUM_REPLICAS = 2
ES_DEFAULT_NUM_SHARDS = 5
ES_COMPRESS = True

# Maximum result position. ES defaults to 10000 but we'd like more to make sure
# all our extensions can be found if searching without a query and
# paginating through all results.
# NOTE: This setting is being set during reindex, if this needs changing
# we need to trigger a reindex. It's also hard-coded in amo/pagination.py
# and there's a test verifying it's value is 30000 in amo/test_pagination.py
ES_MAX_RESULT_WINDOW = 30000

# Default AMO user id to use for tasks.
TASK_USER_ID = 4757633

# Special collection that some contributors can modify.
COLLECTION_FEATURED_THEMES_ID = 2143965

# If this is False, tasks and other jobs that send non-critical emails should
# use a fake email backend.
SEND_REAL_EMAIL = False

STATSD_HOST = env('STATSD_HOST', default='localhost')
STATSD_PREFIX = env('STATSD_PREFIX', default='amo')
STATSD_PORT = 8125

# The django statsd client to use, see django-statsd for more.
STATSD_CLIENT = 'django_statsd.clients.normal'

# Blog URL
DEVELOPER_BLOG_URL = 'https://blog.mozilla.org/addons/wp-json/wp/v2/posts'

LOGIN_RATELIMIT_USER = 5
LOGIN_RATELIMIT_ALL_USERS = '15/m'

CSRF_FAILURE_VIEW = 'olympia.amo.views.csrf_failure'
CSRF_USE_SESSIONS = True

# Default file storage mechanism that holds media.
DEFAULT_FILE_STORAGE = 'olympia.amo.utils.SafeStorage'

# And how long we'll give the server to respond for monitoring.
# We currently do not have any actual timeouts during the signing-process.
SIGNING_SERVER_MONITORING_TIMEOUT = 10

AUTOGRAPH_CONFIG = {
    'server_url': env('AUTOGRAPH_SERVER_URL', default='http://autograph:5500'),
    'user_id': env('AUTOGRAPH_HAWK_USER_ID', default='alice'),
    'key': env(
        'AUTOGRAPH_HAWK_KEY',
        default='fs5wgcer9qj819kfptdlp8gm227ewxnzvsuj9ztycsx08hfhzu',
    ),
    # This is configurable but we don't expect it to be set to anything else
    # but `webextensions-rsa` at this moment because AMO only accepts
    # regular add-ons, no system add-ons or extensions for example. These
    # are already signed when submitted to AMO.
    'signer': env('AUTOGRAPH_SIGNER_ID', default='webextensions-rsa'),
    # This signer is only used for add-ons that are recommended.
    # The signer uses it's own HAWK auth credentials
    'recommendation_signer': env(
        'AUTOGRAPH_RECOMMENDATION_SIGNER_ID',
        default='webextensions-rsa-with-recommendation',
    ),
    'recommendation_signer_user_id': env(
        'AUTOGRAPH_RECOMMENDATION_SIGNER_HAWK_USER_ID', default='bob'
    ),
    'recommendation_signer_key': env(
        'AUTOGRAPH_RECOMMENDATION_SIGNER_HAWK_KEY',
        default='9vh6bhlc10y63ow2k4zke7k0c3l9hpr8mo96p92jmbfqngs9e7d',
    ),
}

# Enable addon signing. Autograph is configured to something reasonable
# when running locally so there aren't many reasons to deactivate that.
ENABLE_ADDON_SIGNING = True

# True when the Django app is running from the test suite.
IN_TEST_SUITE = False

# Temporary flag to work with navigator.mozPay() on devices that don't
# support it natively.
SIMULATE_NAV_PAY = False

# When the dev. agreement gets updated, you need users to re-accept it and the
# config 'last_dev_agreement_change_date' is not set, use this fallback.
# You won't want to do this for minor format changes.
# This value should be updated shortly after new agreement became effective.
# The tuple is passed through to datetime.date, so please use a valid date
# tuple.
DEV_AGREEMENT_CHANGE_FALLBACK = datetime(2025, 8, 4, 0, 0)

# If you want to allow self-reviews for add-ons/apps, then enable this.
# In production we do not want to allow this.
ALLOW_SELF_REVIEWS = False


# Allow URL style format override. eg. "?format=json"
URL_FORMAT_OVERRIDE = 'format'

# Connection to the hive server.
HIVE_CONNECTION = {
    'host': 'peach-gw.peach.metrics.scl3.mozilla.com',
    'port': 10000,
    'user': 'amo_prod',
    'password': '',
    'auth_mechanism': 'PLAIN',
}


STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
)

NODE_MODULES_ROOT = path('node_modules')
NODE_PACKAGE_JSON = path('package.json')
NODE_PACKAGE_MANAGER_INSTALL_OPTIONS = ['--dry-run']

# The manifest file is created in static-build but copied into the static root
# so we should expect to find it at /<static_root/<static_build>/manifest.json
STATIC_BUILD_PATH = path('static-build')
# This value should be kept in sync with vite.config.ts
# where the manifest will be written to
VITE_MANIFEST_FILE_NAME = env('VITE_MANIFEST_FILE_NAME')
STATIC_BUILD_MANIFEST_PATH = path(STATIC_BUILD_PATH, VITE_MANIFEST_FILE_NAME)
STATIC_FILES_PATH = path('static')

STATICFILES_DIRS = (
    STATIC_FILES_PATH,
    STATIC_BUILD_PATH,
)

STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# Path related settings. In dev/stage/prod `NETAPP_STORAGE_ROOT` environment
# variable will be set and point to our NFS/EFS storage
# Make sure to check overwrites in conftest.py if new settings are added
# or changed.
STORAGE_ROOT = env('NETAPP_STORAGE_ROOT', default=path('storage'))
ADDONS_PATH = os.path.join(STORAGE_ROOT, 'files')
MLBF_STORAGE_PATH = os.path.join(STORAGE_ROOT, 'mlbf')
SITEMAP_STORAGE_PATH = os.path.join(STORAGE_ROOT, 'sitemaps')

SHARED_STORAGE = os.path.join(STORAGE_ROOT, 'shared_storage')

MEDIA_ROOT = os.path.join(SHARED_STORAGE, 'uploads')
TMP_PATH = os.path.join(SHARED_STORAGE, 'tmp')

# These are key files that must be present on disk to encrypt/decrypt certain
# database fields.
# {'api_key:secret': os.path.join(ROOT, 'path', 'to', 'file.key'),}
AES_KEYS = env.dict('AES_KEYS', default={})

# Time in seconds for how long a JWT auth token created by developers with
# their API key can live. When developers are creating auth tokens they cannot
# set the expiration any longer than this.
MAX_APIKEY_JWT_AUTH_TOKEN_LIFETIME = 5 * 60

# Time in seconds before the email containing the link allowing developers to
# see their api keys the first time they request one is sent. A value of None
# means it's sent instantaneously.
API_KEY_CONFIRMATION_DELAY = None

# Default cache duration for the API, in seconds.
API_CACHE_DURATION = 6 * 60

# Default cache duration for the API on services.a.m.o., in seconds.
API_CACHE_DURATION_SERVICES = 60 * 60

# JWT authentication related settings:
JWT_AUTH = {
    # Use HMAC using SHA-256 hash algorithm. It should be the default, but we
    # want to make sure it does not change behind our backs.
    # See https://github.com/jpadilla/pyjwt/blob/master/docs/algorithms.rst
    'JWT_ALGORITHM': 'HS256',
    # This adds some padding to timestamp validation in case client/server
    # clocks are off.
    'JWT_LEEWAY': 5,
}

DRF_API_GATES = {
    'auth': (),
    'v3': (
        'ratings-rating-shim',
        'ratings-title-shim',
        'l10n_flat_input_output',
        'collections-downloads-shim',
        'addons-locale_disambiguation-shim',
        'del-addons-created-field',
        'del-accounts-fxa-edit-email-url',
        'del-version-license-is-custom',
        'del-ratings-flags',
        'activity-user-shim',
        'autocomplete-sort-param',
        'is-source-public-shim',
        'is-featured-addon-shim',
        'disco-heading-and-description-shim',
        'wrap-outgoing-parameter',
        'platform-shim',
        'keep-license-text-in-version-list',
        'is-restart-required-shim',
        'is-webextension-shim',
        'version-files',
        'del-version-license-slug',
        'del-preview-position',
        'categories-application',
        'promoted-verified-sponsored',
        'minimal-profile-has-all-fields-shim',
        'promoted-groups-shim',
    ),
    'v4': (
        'l10n_flat_input_output',
        'addons-search-_score-field',
        'ratings-can_reply',
        'ratings-score-filter',
        'wrap-outgoing-parameter',
        'platform-shim',
        'keep-license-text-in-version-list',
        'is-restart-required-shim',
        'is-webextension-shim',
        'version-files',
        'del-version-license-slug',
        'del-preview-position',
        'categories-application',
        'promoted-verified-sponsored',
        'block-min-max-versions-shim',
        'block-versions-list-shim',
        'promoted-groups-shim',
        'minimal-profile-has-all-fields-shim',
    ),
    'v5': (
        'addons-search-_score-field',
        'ratings-can_reply',
        'ratings-score-filter',
        'addon-submission-api',
        'promoted-verified-sponsored',
        'block-versions-list-shim',
    ),
}

# Change this to deactivate API throttling for views using a throttling class
# depending on the one defined in olympia.api.throttling.
API_THROTTLING = True

REST_FRAMEWORK = {
    'ALLOWED_VERSIONS': DRF_API_VERSIONS,
    # Use http://ecma-international.org/ecma-262/5.1/#sec-15.9.1.15
    # We can't use the default because we don't use django timezone support.
    'DATETIME_FORMAT': '%Y-%m-%dT%H:%M:%SZ',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'olympia.api.authentication.SessionIDAuthentication',
    ),
    'DEFAULT_PAGINATION_CLASS': ('olympia.api.pagination.CustomPageNumberPagination'),
    # Use json by default when using APIClient.
    # Set this because the default is to also include:
    #   'rest_framework.renderers.BrowsableAPIRenderer'
    # Which it will try to use if the client accepts text/html.
    'DEFAULT_RENDERER_CLASSES': ('rest_framework.renderers.JSONRenderer',),
    'DEFAULT_VERSION': 'v5',
    'DEFAULT_VERSIONING_CLASS': ('rest_framework.versioning.NamespaceVersioning'),
    # Add our custom exception handler, that wraps all exceptions into
    # Responses and not just the ones that are api-related.
    'EXCEPTION_HANDLER': 'olympia.api.exceptions.custom_exception_handler',
    # Explictly set the number of proxies
    'NUM_PROXIES': 0,
    # Set our default ordering parameter
    'ORDERING_PARAM': 'sort',
    # Enable pagination
    'PAGE_SIZE': 25,
    # Use our pagination class by default, which allows clients to request a
    # different page size.
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',
    # register spectacular AutoSchema with DRF.
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# We need to load this before sentry_sdk.init or our reverse replacement is too late.
from olympia.amo import reverse  # noqa


sentry_sdk.init(
    integrations=[DjangoIntegration(), CeleryIntegration()],
    **olympia.core.sentry.get_sentry_config(env),
)
ignore_logger('django.security.DisallowedHost')

# Automatically do 'from olympia import amo' when running shell_plus.
SHELL_PLUS_POST_IMPORTS = (('olympia', 'amo'),)

FXA_CONFIG = {
    'default': {
        'client_id': env('FXA_CLIENT_ID', default=''),
        'client_secret': env('FXA_CLIENT_SECRET', default=''),
        # fxa redirects to https://%s/api/auth/authenticate-callback/ % DOMAIN
    },
}
DEFAULT_FXA_CONFIG_NAME = 'default'

FXA_CONTENT_HOST = 'https://accounts.firefox.com'
FXA_OAUTH_HOST = 'https://oauth.accounts.firefox.com/v1'
FXA_PROFILE_HOST = 'https://profile.accounts.firefox.com/v1'

USE_FAKE_FXA_AUTH = False  # Should only be True for local development envs.
VERIFY_FXA_ACCESS_TOKEN = True

# List all jobs that should be callable with cron here.
# syntax is: job_and_method_name: full.package.path
CRON_JOBS = {
    'addon_last_updated': 'olympia.addons.cron',
    'flag_high_rating_addons': 'olympia.ratings.cron',
    'gc': 'olympia.amo.cron',
    'process_blocklistsubmissions': 'olympia.blocklist.cron',
    'record_reviewer_queues_counts': 'olympia.reviewers.cron',
    'sync_suppressed_emails_cron': 'olympia.users.cron',
    'update_addon_average_daily_users': 'olympia.addons.cron',
    'update_addon_hotness': 'olympia.addons.cron',
    'update_addon_weekly_downloads': 'olympia.addons.cron',
    'update_blog_posts': 'olympia.devhub.cron',
    'update_user_ratings': 'olympia.users.cron',
    'upload_mlbf_to_remote_settings': 'olympia.blocklist.cron',
    'write_sitemaps': 'olympia.amo.cron',
}

# Reputation service is disabled by default, enabled for dev/stage/prod via
# those 3 env variables.
REPUTATION_SERVICE_URL = env('REPUTATION_SERVICE_URL', default=None)
REPUTATION_SERVICE_TOKEN = env('REPUTATION_SERVICE_TOKEN', default=None)
REPUTATION_SERVICE_TIMEOUT = env.float('REPUTATION_SERVICE_TIMEOUT', default=1)

BASKET_URL = env('BASKET_URL', default='https://basket.allizom.org')
BASKET_API_KEY = env('BASKET_API_KEY', default=None)
# Default is 10, the API usually answers in 0.5 - 1.5 seconds.
BASKET_TIMEOUT = 5
MOZILLA_NEWLETTER_URL = env(
    'MOZILLA_NEWSLETTER_URL', default='https://www.mozilla.org/en-US/newsletter/'
)

EXTENSION_WORKSHOP_URL = env(
    'EXTENSION_WORKSHOP_URL', default='https://extensionworkshop.allizom.org'
)

# Sectools
SCANNER_TIMEOUT = 60  # seconds
CUSTOMS_API_URL = env('CUSTOMS_API_URL', default=None)
CUSTOMS_API_KEY = env('CUSTOMS_API_KEY', default=None)
# Git(Hub) repository names, e.g., `owner/repo-name`
CUSTOMS_GIT_REPOSITORY = env('CUSTOMS_GIT_REPOSITORY', default=None)

# Addon.average_daily_user count that forces dual sign-off for Blocklist Blocks
DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD = 100_000
REMOTE_SETTINGS_API_URL = 'https://remote-settings-dev.allizom.org/v1/'
REMOTE_SETTINGS_WRITER_URL = 'https://remote-settings-dev.allizom.org/v1/'
REMOTE_SETTINGS_WRITER_BUCKET = 'staging'
REMOTE_SETTINGS_CHECK_TIMEOUT_SECONDS = 10

# Each env is expected to overwrite those credentials.
BLOCKLIST_REMOTE_SETTINGS_USERNAME = env(
    'BLOCKLIST_KINTO_USERNAME', default='amo_remote_settings_username'
)
BLOCKLIST_REMOTE_SETTINGS_PASSWORD = env(
    'BLOCKLIST_KINTO_PASSWORD', default='amo_remote_settings_password'
)

# The path to the current google service account configuration for BigQuery.
# This is being used to query Google BigQuery as part of our stats processing.
# If this is `None` we're going to use service mocks for testing
GOOGLE_APPLICATION_CREDENTIALS_BIGQUERY = env(
    'GOOGLE_APPLICATION_CREDENTIALS_BIGQUERY',
    default=env('GOOGLE_APPLICATION_CREDENTIALS', default=None),
)
# See: https://bugzilla.mozilla.org/show_bug.cgi?id=1633746
BIGQUERY_PROJECT = 'moz-fx-data-shared-prod'
BIGQUERY_AMO_DATASET = 'amo_dev'

# The path to the current google service account configuration for Google Cloud
# Storage (should be able to upload, download and sign objects with its private
# key).
# This is being used to store copies of content being reported/banned.
# If this is `None` we're going to use service mocks for testing
GOOGLE_APPLICATION_CREDENTIALS_STORAGE = env(
    'GOOGLE_APPLICATION_CREDENTIALS_STORAGE', default=None
)
GOOGLE_STORAGE_REPORTED_CONTENT_BUCKET = env(
    'GOOGLE_STORAGE_REPORTED_CONTENT_BUCKET', default=None
)

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

SITEMAP_DEBUG_AVAILABLE = False

CINDER_SERVER_URL = env('CINDER_SERVER_URL', default=None)
CINDER_API_TOKEN = env('CINDER_API_TOKEN', default=None)
CINDER_WEBHOOK_TOKEN = env('CINDER_WEBHOOK_TOKEN', default=None)
CINDER_QUEUE_PREFIX = 'amo-dev-'
# Because our stage Cinder instance is shared between addons-dev, addons stage, and also
# any local testing integration, entity ids are not unique, and a payload from the
# webhook may return ids for a given cinder job or decision that are not valid simply
# because it doesn't originate from the same environment that the webhook is registered
# for. When False we don't return a 400 for an invalid ID, to not pollute the logs with
# false positives.
CINDER_UNIQUE_IDS = False

SOCKET_LABS_HOST = env('SOCKET_LABS_HOST', default='https://api.socketlabs.com/v2/')
SOCKET_LABS_TOKEN = env('SOCKET_LABS_TOKEN', default=None)
SOCKET_LABS_SERVER_ID = env('SOCKET_LABS_SERVER_ID', default=None)

# Set to True in settings_test.py
# This controls the behavior of migrations
TESTING_ENV = False

ENABLE_ADMIN_MLBF_UPLOAD = False

DJANGO_VITE = {
    'default': {
        'manifest_path': STATIC_BUILD_MANIFEST_PATH,
    }
}

# The environment in which the application is running.
# This is set by the environment variables in production environments.
# For local it is hard coded to "local" in `docker-compose.yml` to guarantee a clear
# distinction between local and non-local environments.
ENV = env('ENV')

MEMCACHE_MIN_SERVER_COUNT = 2

SPECTACULAR_SETTINGS = {
    # Extract tag of the root path of the API route
    # /api/v5/foo -> foo
    'SCHEMA_PATH_PREFIX': '/api/v[0-9]',
    'TITLE': 'AMO API (Experimental)',
    'DESCRIPTION': (
        'Addons Server API Documentation (Experimental, check out '
        '<a href="https://mozilla.github.io/addons-server/topics/api/index.html">'
        'official documentation</a> for a more reliable source of information)'
    ),
    'SERVE_INCLUDE_SCHEMA': True,
    'SERVE_PERMISSIONS': ['rest_framework.permissions.AllowAny'],
    # load swagger/redoc assets via collectstatic assets
    # rather than via the CDN
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
}

SWAGGER_SCHEMA_FILE = path('schema.yml')

SWAGGER_UI_ENABLED = env('SWAGGER_UI_ENABLED', default=False) or TARGET != 'production'

