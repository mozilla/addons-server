# -*- coding: utf-8 -*-
# Django settings for addons-server project.

import environ
import json
import logging
import os
import socket

from datetime import datetime

import raven
from kombu import Queue

import olympia.core.logger


env = environ.Env()

ENVIRON_SETTINGS_FILE_PATH = '/etc/olympia/settings.env'

if os.path.exists(ENVIRON_SETTINGS_FILE_PATH):
    env.read_env(env_file=ENVIRON_SETTINGS_FILE_PATH)


ALLOWED_HOSTS = [
    '.allizom.org',
    '.mozilla.org',
    '.mozilla.com',
    '.mozilla.net',
    '.mozaws.net',
]

# jingo-minify settings
CACHEBUST_IMGS = True
try:
    # If we have build ids available, we'll grab them here and add them to our
    # CACHE_KEY_PREFIX. This will let us not have to flush memcache during
    # updates and it will let us preload data into it before a production push.
    from build import BUILD_ID_CSS, BUILD_ID_JS
    build_id = "%s%s" % (BUILD_ID_CSS[:2], BUILD_ID_JS[:2])
except ImportError:
    build_id = ""

# jingo-minify: Style sheet media attribute default
CSS_MEDIA_DEFAULT = 'all'

# Make filepaths relative to the root of olympia.
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
ROOT = os.path.join(BASE_DIR, '..', '..')


def path(*folders):
    return os.path.join(ROOT, *folders)


DEBUG = False

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
)

# LESS CSS OPTIONS (Debug only).
LESS_PREPROCESS = True  # Compile LESS with Node, rather than client-side JS?
LESS_LIVE_REFRESH = False  # Refresh the CSS on save?
LESS_BIN = env(
    'LESS_BIN', default='node_modules/less/bin/lessc')

# Path to cleancss (our CSS minifier).
CLEANCSS_BIN = env(
    'CLEANCSS_BIN', default='node_modules/less/bin/lessc')

# Path to uglifyjs (our JS minifier).
# Set as None to use YUI instead (at your risk).
UGLIFY_BIN = env(
    'UGLIFY_BIN', default='node_modules/uglify-js/bin/uglifyjs')

# rsvg-convert is used to save our svg static theme previews to png
RSVG_CONVERT_BIN = env('RSVG_CONVERT_BIN', default='rsvg-convert')

# Path to pngcrush (to optimize the PNGs uploaded by developers).
PNGCRUSH_BIN = env('PNGCRUSH_BIN', default='pngcrush')

# Path to our addons-linter binary
ADDONS_LINTER_BIN = env(
    'ADDONS_LINTER_BIN',
    default='node_modules/addons-linter/bin/addons-linter')

DELETION_EMAIL = 'amo-notifications+deletion@mozilla.org'
THEMES_EMAIL = 'theme-reviews@mozilla.org'

DRF_API_VERSIONS = ['auth', 'v3', 'v4', 'v5']
DRF_API_REGEX = r'^/?api/(?:auth|v3|v4|v5)/'

# Add Access-Control-Allow-Origin: * header for the new API with
# django-cors-headers.
CORS_ORIGIN_ALLOW_ALL = True
# Exclude the `accounts/session` endpoint, see:
# https://github.com/mozilla/addons-server/issues/11100
CORS_URLS_REGEX = r'{}(?!accounts/session/)'.format(DRF_API_REGEX)


def get_db_config(environ_var, atomic_requests=True):
    values = env.db(
        var=environ_var,
        default='mysql://root:@localhost/olympia')

    values.update({
        # Run all views in a transaction unless they are decorated not to.
        # `atomic_requests` should be `False` for database replicas where no
        # write operations will ever happen.
        'ATOMIC_REQUESTS': atomic_requests,
        # Pool our database connections up for 300 seconds
        'CONN_MAX_AGE': 300,
        'ENGINE': 'olympia.core.db.mysql',
        'OPTIONS': {
            'charset': 'utf8mb4',
            'sql_mode': 'STRICT_ALL_TABLES',
            'isolation_level': 'read committed'
        },
        'TEST': {
            'CHARSET': 'utf8mb4',
            'COLLATION': 'utf8mb4_general_ci'
        },
    })

    return values


DATABASES = {
    'default': get_db_config('DATABASES_DEFAULT_URL'),
}

# A database to be used by the services scripts, which does not use Django.
# Please note that this is not a full Django database connection
# so the amount of values supported are limited. By default we are using
# the same connection as 'default' but that changes in prod/dev/stage.
SERVICES_DATABASE = get_db_config('DATABASES_DEFAULT_URL')

DATABASE_ROUTERS = ('multidb.PinningReplicaRouter',)

# Put the aliases for your slave databases in this list.
REPLICA_DATABASES = []

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
from olympia.core.languages import LANGUAGE_MAPPING  # noqa
AMO_LANGUAGES = LANGUAGE_MAPPING.keys()

# Bidirectional languages.
# Locales in here *must* be in `AMO_LANGUAGES` too.
LANGUAGES_BIDI = ('ar', 'fa', 'he', 'ur')

# Explicit conversion of a shorter language code into a more specific one.
SHORTER_LANGUAGES = {
    'en': 'en-US', 'ga': 'ga-IE', 'pt': 'pt-PT', 'sv': 'sv-SE', 'zh': 'zh-CN'
}

# Override Django's built-in with our native names
LANGUAGES = {
    locale.lower(): value['native']
    for locale, value in LANGUAGE_MAPPING.items()}

LANGUAGE_URL_MAP = {
    locale.lower(): locale
    for locale in AMO_LANGUAGES}

LOCALE_PATHS = (
    path('locale'),
)

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# The host currently running the site.  Only use this in code for good reason;
# the site is designed to run on a cluster and should continue to support that
HOSTNAME = socket.gethostname()

# The front end domain of the site. If you're not running on a cluster this
# might be the same as HOSTNAME but don't depend on that.  Use this when you
# need the real domain.
DOMAIN = HOSTNAME

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

# URL of the code-manager site, see:
# https://github.com/mozilla/addons-code-manager
CODE_MANAGER_URL = 'https://code.{}'.format(DOMAIN)

# Filter IP addresses of allowed clients that can post email through the API.
ALLOWED_CLIENTS_EMAIL_API = env.list('ALLOWED_CLIENTS_EMAIL_API', default=[])
# Auth token required to authorize inbound email.
INBOUND_EMAIL_SECRET_KEY = env('INBOUND_EMAIL_SECRET_KEY', default='')
# Validation key we need to send in POST response.
INBOUND_EMAIL_VALIDATION_KEY = env('INBOUND_EMAIL_VALIDATION_KEY', default='')
# Domain emails should be sent to.
INBOUND_EMAIL_DOMAIN = env('INBOUND_EMAIL_DOMAIN', default=DOMAIN)

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = '/user-media/'

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
    'about', 'admin', 'apps', 'contribute.json',
    'developer_agreement', 'developers', 'editors',
    'review_guide', 'google1f3e37b7351799a5.html',
    'google231a41e803e464e9.html', 'reviewers', 'robots.txt', 'statistics',
    'services', 'static', 'user-media', '__version__',
)
DEFAULT_APP = 'firefox'

# paths that don't require a locale prefix
# This needs to be kept in sync with addons-frontend's validLocaleUrlExceptions
# https://github.com/mozilla/addons-frontend/blob/master/config/default-amo.js
SUPPORTED_NONLOCALES = (
    'contribute.json', 'google1f3e37b7351799a5.html',
    'google231a41e803e464e9.html', 'robots.txt', 'services', 'downloads',
    'static', 'user-media', '__version__',
)

# Make this unique, and don't share it with anybody.
SECRET_KEY = env(
    'SECRET_KEY',
    default='this-is-a-dummy-key-and-its-overridden-for-prod-servers')

# Templates configuration.
# List of path patterns for which we should be using Django Template Language.
JINJA_EXCLUDE_TEMPLATE_PATHS = (
    # All emails should be processed with Django for consistency.
    r'^.*\/emails\/',

    # ^admin\/ covers most django admin templates, since their path should
    # follow /admin/<app>/<model>/*
    r'^admin\/',

    # Third-party apps + django.
    r'debug_toolbar',
    r'^rangefilter\/',
    r'^registration\/',
)

TEMPLATES = [
    {
        'BACKEND': 'django_jinja.backend.Jinja2',
        'NAME': 'jinja2',
        'APP_DIRS': True,
        'DIRS': (
            path('media', 'docs'),
            path('src/olympia/templates'),
        ),
        'OPTIONS': {
            # http://jinja.pocoo.org/docs/dev/extensions/#newstyle-gettext
            'newstyle_gettext': True,
            # Match our regular .html and .txt file endings except
            # for the admin and a handful of other paths
            'match_extension': None,
            'match_regex': r'^(?!({paths})).*'.format(
                paths='|'.join(JINJA_EXCLUDE_TEMPLATE_PATHS)),
            'context_processors': (
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.debug',
                'django.template.context_processors.media',
                'django.template.context_processors.request',

                'django.contrib.messages.context_processors.messages',

                'olympia.amo.context_processors.i18n',
                'olympia.amo.context_processors.global_settings',
                'olympia.amo.context_processors.static_url',
                'olympia.lib.jingo_minify_helpers.build_ids',
            ),
            'extensions': (
                'jinja2.ext.autoescape',
                'jinja2.ext.do',
                'jinja2.ext.loopcontrols',
                'jinja2.ext.with_',
                'django_jinja.builtins.extensions.CsrfExtension',
                'django_jinja.builtins.extensions.DjangoFiltersExtension',
                'django_jinja.builtins.extensions.StaticFilesExtension',
                'django_jinja.builtins.extensions.TimezoneExtension',
                'django_jinja.builtins.extensions.UrlsExtension',
                'puente.ext.i18n',
                'waffle.jinja.WaffleExtension',
            ),
            'finalize': lambda x: x if x is not None else '',
            'translation_engine': 'django.utils.translation',
            'autoescape': True,
            'trim_blocks': True,
        }
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
        }
    },
]


X_FRAME_OPTIONS = 'DENY'
SECURE_BROWSER_XSS_FILTER = True
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
    'olympia.api.middleware.IdentifyAPIRequestMiddleware',
    # Gzip (for API only) middleware needs to be executed after every
    # modification to the response, so it's placed at the top of the list.
    'olympia.api.middleware.GZipMiddlewareForAPIOnly',

    # Statsd and logging come first to get timings etc. Munging REMOTE_ADDR
    # must come before middlewares potentially using REMOTE_ADDR, so it's
    # also up there.
    'django_statsd.middleware.GraphiteRequestTimingMiddleware',
    'django_statsd.middleware.GraphiteMiddleware',
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
    'csp.middleware.CSPMiddleware',
    'corsheaders.middleware.CorsMiddleware',

    # Enable conditional processing, e.g ETags.
    'django.middleware.http.ConditionalGetMiddleware',

    'olympia.amo.middleware.CommonMiddleware',
    'olympia.amo.middleware.NoVarySessionMiddleware',
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
    'olympia.ratings',
    'olympia.reviewers',
    'olympia.scanners',
    'olympia.search',
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
    'raven.contrib.django',
    'rest_framework',
    'waffle',
    'django_jinja',
    'puente',
    'rangefilter',

    # Django contrib apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.messages',
    'django.contrib.sessions',
    'django.contrib.staticfiles',

    # Has to load after auth
    'django_statsd',
)

# These need to point to prod, because that's where the database lives. You can
# change it locally to test the extraction process, but be careful not to
# accidentally nuke translations when doing that!
DISCOVERY_EDITORIAL_CONTENT_API = (
    'https://addons.mozilla.org/api/v4/discovery/editorial/')
SECONDARY_HERO_EDITORIAL_CONTENT_API = (
    'https://addons.mozilla.org/api/v4/hero/secondary/?all=true')

# Filename where the strings will be stored. Used in puente config below.
EDITORIAL_CONTENT_FILENAME = 'src/olympia/discovery/strings.jinja2'

# Tells the extract script what files to look for l10n in and what function
# handles the extraction. The puente library expects this.
PUENTE = {
    'BASE_DIR': ROOT,
    # Tells the extract script what files to look for l10n in and what function
    # handles the extraction.
    'DOMAIN_METHODS': {
        'django': [
            ('src/olympia/**.py', 'python'),

            # Extract the generated file containing editorial content for all
            # disco pane recommendations using jinja2 parser. It's not a real
            # template, but it uses jinja2 syntax for convenience, hence why
            # it's not in templates/ with a .html extension.
            (EDITORIAL_CONTENT_FILENAME, 'jinja2'),

            # Make sure we're parsing django-admin & email templates with the
            # django template extractor. This should match the behavior of
            # JINJA_EXCLUDE_TEMPLATE_PATHS
            (
                'src/olympia/**/templates/**/emails/**.*',
                'django_babel.extract.extract_django'
            ),
            (
                '**/templates/admin/**.html',
                'django_babel.extract.extract_django'
            ),

            ('src/olympia/**/templates/**.html', 'jinja2'),
        ],
        'djangojs': [
            # We can't say **.js because that would dive into mochikit
            # and timeplot and all the other baggage we're carrying.
            # Timeplot, in particular, crashes the extractor with bad
            # unicode data.
            ('static/js/**-all.js', 'ignore'),
            ('static/js/**-min.js', 'ignore'),
            ('static/js/*.js', 'javascript'),
            ('static/js/amo2009/**.js', 'javascript'),
            ('static/js/common/**.js', 'javascript'),
            ('static/js/impala/**.js', 'javascript'),
            ('static/js/zamboni/**.js', 'javascript'),
        ],
    },
}

# Bundles is a dictionary of two dictionaries, css and js, which list css files
# and js files that can be bundled together by the minify app.
MINIFY_BUNDLES = {
    'css': {
        'restyle/css': (
            'css/restyle/restyle.less',
        ),

        # CSS files our DevHub (currently only required for the
        # new landing page)
        'devhub/new-landing/css': (
            'css/devhub/new-landing/base.less',
        ),

        # Responsive error page styling.
        'errors/css': (
            'css/errors/base.less',
        ),

        # CSS files common to the entire site.
        'zamboni/css': (
            'css/legacy/main.css',
            'css/legacy/main-mozilla.css',
            'css/legacy/jquery-lightbox.css',
            'css/zamboni/zamboni.css',
            'css/zamboni/tags.css',
            'css/zamboni/tabs.css',
            'css/impala/buttons.less',
            'css/impala/formset.less',
            'css/impala/suggestions.less',
            'css/impala/header.less',
            'css/impala/moz-tab.css',
            'css/impala/footer.less',
            'css/impala/faux-zamboni.less',
        ),
        'zamboni/impala': (
            'css/impala/base.css',
            'css/legacy/jquery-lightbox.css',
            'css/impala/site.less',
            'css/impala/typography.less',
            'css/impala/forms.less',
            'css/common/invisible-upload.less',
            'css/impala/header.less',
            'css/impala/footer.less',
            'css/impala/moz-tab.css',
            'css/impala/hovercards.less',
            'css/impala/toplist.less',
            'css/impala/carousel.less',
            'css/impala/ratings.less',
            'css/impala/buttons.less',
            'css/impala/promos.less',
            'css/impala/addon_details.less',
            'css/impala/policy.less',
            'css/impala/expando.less',
            'css/impala/popups.less',
            'css/impala/l10n.less',
            'css/impala/lightbox.less',
            'css/impala/prose.less',
            'css/impala/abuse.less',
            'css/impala/paginator.less',
            'css/impala/listing.less',
            'css/impala/versions.less',
            'css/impala/users.less',
            'css/impala/tooltips.less',
            'css/impala/search.less',
            'css/impala/suggestions.less',
            'css/node_lib/jquery.minicolors.css',
            'css/impala/login.less',
            'css/impala/dictionaries.less',
            'css/impala/apps.less',
            'css/impala/formset.less',
            'css/impala/tables.less',
            'css/impala/compat.less',
        ),
        'zamboni/stats': (
            'css/impala/stats.less',
        ),
        'zamboni/discovery-pane': (
            'css/impala/promos.less',
            'css/legacy/jquery-lightbox.css',
        ),
        'zamboni/devhub': (
            'css/impala/tooltips.less',
            'css/zamboni/developers.css',
            'css/zamboni/docs.less',
            'css/impala/developers.less',
            'css/devhub/listing.less',
            'css/devhub/popups.less',
            'css/devhub/compat.less',
            'css/impala/formset.less',
            'css/devhub/forms.less',
            'css/common/invisible-upload.less',
            'css/devhub/submission.less',
            'css/devhub/refunds.less',
            'css/devhub/buttons.less',
            'css/devhub/in-app-config.less',
            'css/devhub/static-theme.less',
            'css/node_lib/jquery.minicolors.css',
        ),
        'zamboni/devhub_impala': (
            'css/impala/developers.less',
            'css/devhub/listing.less',
            'css/devhub/popups.less',
            'css/devhub/compat.less',
            'css/devhub/dashboard.less',
            'css/devhub/forms.less',
            'css/common/invisible-upload.less',
            'css/devhub/submission.less',
            'css/devhub/search.less',
            'css/devhub/refunds.less',
            'css/impala/devhub-api.less',
        ),
        'zamboni/reviewers': (
            'css/zamboni/reviewers.less',
            'css/zamboni/unlisted.less',
        ),
        'zamboni/themes_review': (
            'css/zamboni/developers.css',
            'css/zamboni/reviewers.less',
            'css/zamboni/themes_review.less',
        ),
        'zamboni/files': (
            'css/lib/syntaxhighlighter/shCoreDefault.css',
            'css/zamboni/files.css',
        ),
        'zamboni/admin': (
            'css/zamboni/admin-django.css',
            'css/zamboni/admin-mozilla.css',
            'css/zamboni/admin_features.css',
        ),
    },
    'js': {
        # JS files common to the entire site, apart from dev-landing.
        'common': (
            'js/node_lib/underscore.js',
            'js/zamboni/browser.js',
            'js/amo2009/addons.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/lib/format.js',
            'js/node_lib/jquery.cookie.js',
            'js/zamboni/storage.js',
            'js/zamboni/buttons.js',
            'js/zamboni/tabs.js',
            'js/common/keys.js',

            # jQuery UI
            'js/node_lib/ui/version.js',
            'js/node_lib/ui/data.js',
            'js/node_lib/ui/disable-selection.js',
            'js/node_lib/ui/ie.js',
            'js/node_lib/ui/keycode.js',
            'js/node_lib/ui/escape-selector.js',
            'js/node_lib/ui/labels.js',
            'js/node_lib/ui/jquery-1-7.js',
            'js/node_lib/ui/plugin.js',
            'js/node_lib/ui/safe-active-element.js',
            'js/node_lib/ui/safe-blur.js',
            'js/node_lib/ui/scroll-parent.js',
            'js/node_lib/ui/focusable.js',
            'js/node_lib/ui/tabbable.js',
            'js/node_lib/ui/unique-id.js',
            'js/node_lib/ui/position.js',
            'js/node_lib/ui/widget.js',
            'js/node_lib/ui/menu.js',
            'js/node_lib/ui/mouse.js',
            'js/node_lib/ui/autocomplete.js',
            'js/node_lib/ui/datepicker.js',
            'js/node_lib/ui/sortable.js',

            'js/zamboni/helpers.js',
            'js/common/banners.js',
            'js/zamboni/global.js',
            'js/amo2009/global.js',
            'js/common/ratingwidget.js',
            'js/node_lib/jqModal.js',
            'js/zamboni/l10n.js',
            'js/zamboni/debouncer.js',

            # Homepage
            'js/zamboni/homepage.js',

            # Add-ons details page
            'js/lib/ui.lightbox.js',
            'js/zamboni/addon_details.js',
            'js/impala/abuse.js',
            'js/zamboni/ratings.js',

            'js/lib/jquery.hoverIntent.js',

            # Unicode letters for our makeslug function
            'js/zamboni/unicode.js',

            # Users
            'js/zamboni/users.js',

            # Search suggestions
            'js/impala/forms.js',
            'js/impala/ajaxcache.js',
            'js/impala/suggestions.js',
            'js/impala/site_suggestions.js',
        ),

        # Impala and Legacy: Things to be loaded at the top of the page
        'preload': (
            'js/node_lib/jquery.js',
            'js/node_lib/jquery.browser.js',
            'js/impala/preloaded.js',
            'js/zamboni/analytics.js',
        ),
        # Impala: Things to be loaded at the bottom
        'impala': (
            'js/lib/ngettext-overload.js',
            'js/node_lib/underscore.js',
            'js/impala/carousel.js',
            'js/zamboni/browser.js',
            'js/amo2009/addons.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/lib/format.js',
            'js/node_lib/jquery.cookie.js',
            'js/zamboni/storage.js',
            'js/zamboni/buttons.js',
            'js/node_lib/jquery.pjax.js',
            # jquery.pjax.js is missing a semicolon at the end which breaks
            # our wonderful minification process... so add one.
            'js/lib/semicolon.js',  # It's just a semicolon!
            'js/impala/footer.js',
            'js/common/keys.js',

            # jQuery UI
            'js/node_lib/ui/version.js',
            'js/node_lib/ui/data.js',
            'js/node_lib/ui/disable-selection.js',
            'js/node_lib/ui/ie.js',
            'js/node_lib/ui/keycode.js',
            'js/node_lib/ui/escape-selector.js',
            'js/node_lib/ui/labels.js',
            'js/node_lib/ui/jquery-1-7.js',
            'js/node_lib/ui/plugin.js',
            'js/node_lib/ui/safe-active-element.js',
            'js/node_lib/ui/safe-blur.js',
            'js/node_lib/ui/scroll-parent.js',
            'js/node_lib/ui/focusable.js',
            'js/node_lib/ui/tabbable.js',
            'js/node_lib/ui/unique-id.js',
            'js/node_lib/ui/position.js',
            'js/node_lib/ui/widget.js',
            'js/node_lib/ui/mouse.js',
            'js/node_lib/ui/menu.js',
            'js/node_lib/ui/autocomplete.js',
            'js/node_lib/ui/datepicker.js',
            'js/node_lib/ui/sortable.js',

            'js/lib/truncate.js',
            'js/zamboni/truncation.js',
            'js/impala/ajaxcache.js',
            'js/zamboni/helpers.js',
            'js/common/banners.js',
            'js/zamboni/global.js',
            'js/impala/global.js',
            'js/common/ratingwidget.js',
            'js/node_lib/jqModal.js',
            'js/zamboni/l10n.js',
            'js/impala/forms.js',

            # Homepage
            'js/impala/homepage.js',

            # Add-ons details page
            'js/lib/ui.lightbox.js',
            'js/impala/addon_details.js',
            'js/impala/abuse.js',
            'js/impala/ratings.js',

            # Browse listing pages
            'js/impala/listing.js',

            'js/lib/jquery.hoverIntent.js',

            'js/common/upload-image.js',
            'js/node_lib/jquery.minicolors.js',

            # Unicode letters for our makeslug function
            'js/zamboni/unicode.js',

            # Users
            'js/zamboni/users.js',
            'js/impala/users.js',

            # Search
            'js/impala/serializers.js',
            'js/impala/search.js',
            'js/impala/suggestions.js',
            'js/impala/site_suggestions.js',

            # Login
            'js/impala/login.js',
        ),
        'zamboni/discovery': (
            'js/node_lib/jquery.js',
            'js/node_lib/jquery.browser.js',
            'js/node_lib/underscore.js',
            'js/zamboni/browser.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/lib/format.js',
            'js/impala/carousel.js',
            'js/zamboni/analytics.js',

            # Add-ons details
            'js/node_lib/jquery.cookie.js',
            'js/zamboni/storage.js',
            'js/zamboni/buttons.js',
            'js/lib/ui.lightbox.js',

            'js/lib/jquery.hoverIntent.js',

            'js/zamboni/debouncer.js',
            'js/lib/truncate.js',
            'js/zamboni/truncation.js',
        ),
        'zamboni/devhub': (
            'js/lib/truncate.js',
            'js/zamboni/truncation.js',
            'js/common/upload-base.js',
            'js/common/upload-addon.js',
            'js/common/upload-image.js',
            'js/impala/formset.js',
            'js/zamboni/devhub.js',
            'js/zamboni/validator.js',
            'js/node_lib/jquery.timeago.js',
            'js/zamboni/static_theme.js',
            'js/node_lib/jquery.minicolors.js',
            'js/node_lib/jszip.js',
        ),
        'devhub/new-landing/js': (
            'js/common/lang_switcher.js',
            'js/lib/basket-client.js',
        ),
        'zamboni/reviewers': (
            'js/lib/highcharts.src.js',
            'js/lib/jquery.hoverIntent.js',  # Used by jquery.zoomBox.
            'js/lib/jquery.zoomBox.js',  # Used by themes_review.
            'js/zamboni/reviewers.js',
            'js/zamboni/themes_review_templates.js',
            'js/zamboni/themes_review.js',
        ),
        'zamboni/files': (
            'js/lib/diff_match_patch_uncompressed.js',
            'js/lib/syntaxhighlighter/shCore.js',
            'js/lib/syntaxhighlighter/shLegacy.js',
            'js/lib/syntaxhighlighter/shBrushCss.js',
            'js/lib/syntaxhighlighter/shBrushJava.js',
            'js/lib/syntaxhighlighter/shBrushJScript.js',
            'js/lib/syntaxhighlighter/shBrushPlain.js',
            'js/lib/syntaxhighlighter/shBrushXml.js',
            'js/zamboni/storage.js',
            'js/zamboni/files_templates.js',
            'js/zamboni/files.js',
        ),
        'zamboni/stats': (
            'js/lib/highcharts.src.js',
            'js/impala/stats/csv_keys.js',
            'js/impala/stats/helpers.js',
            'js/impala/stats/dateutils.js',
            'js/impala/stats/manager.js',
            'js/impala/stats/controls.js',
            'js/impala/stats/overview.js',
            'js/impala/stats/topchart.js',
            'js/impala/stats/chart.js',
            'js/impala/stats/table.js',
            'js/impala/stats/stats.js',
        ),
        'zamboni/admin': (
            'js/zamboni/admin.js',
            'js/zamboni/admin_features.js',
            'js/zamboni/admin_validation.js',
        ),
        # This is included when DEBUG is True.  Bundle in <head>.
        'debug': (
            'js/debug/less_setup.js',
            'js/node_lib/less.js',
            'js/debug/less_live.js',
        ),
    }
}

# Prefix for cache keys (will prevent collisions when running parallel copies)
# This value is being used by `conf/settings/{dev,stage,prod}.py
CACHE_KEY_PREFIX = 'amo:%s:' % build_id

CACHE_MIDDLEWARE_KEY_PREFIX = CACHE_KEY_PREFIX
FETCH_BY_ID = True

# Number of seconds a count() query should be cached.  Keep it short because
# it's not possible to invalidate these queries.
CACHE_COUNT_TIMEOUT = 60

# To enable pylibmc compression (in bytes)
PYLIBMC_MIN_COMPRESS_LEN = 0  # disabled

# External tools.
JAVA_BIN = '/usr/bin/java'

# File paths
ADDON_ICONS_DEFAULT_PATH = os.path.join(ROOT, 'static', 'img', 'addon-icons')

# URL paths
# paths for images, e.g. mozcdn.com/amo or '/static'
VAMO_URL = 'https://versioncheck.addons.mozilla.org'


# Outgoing URL bouncer
REDIRECT_URL = 'https://outgoing.prod.mozaws.net/v1/'
REDIRECT_SECRET_KEY = env('REDIRECT_SECRET_KEY', default='')

# Allow URLs from these servers. Use full domain names.
REDIRECT_URL_ALLOW_LIST = ['addons.mozilla.org']

# Default to short expiration; check "remember me" to override
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
# See: https://github.com/mozilla/addons-server/issues/1789
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
# This value must be kept in sync with authTokenValidFor from addons-frontend:
# https://github.com/mozilla/addons-frontend/blob/2f480b474fe13a676237fe76a1b2a057e4a2aac7/config/default-amo.js#L111
SESSION_COOKIE_AGE = 2592000  # 30 days
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN  # bug 608797
MESSAGE_STORAGE = 'django.contrib.messages.storage.cookie.CookieStorage'

# These should have app+locale at the start to avoid redirects
LOGIN_URL = '/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
# When logging in with browser ID, a username is created automatically.
# In the case of duplicates, the process is recursive up to this number
# of times.
MAX_GEN_USERNAME_TRIES = 50

# Email settings
ADDONS_EMAIL = "Mozilla Add-ons <nobody@mozilla.org>"
DEFAULT_FROM_EMAIL = ADDONS_EMAIL

# Email goes to the console by default.  s/console/smtp/ for regular delivery
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Please use all lowercase for the QA allow list.
EMAIL_QA_ALLOW_LIST = env.list('EMAIL_QA_ALLOW_LIST', default=())
# Please use all lowercase for the deny_list.
EMAIL_DENY_LIST = env.list('EMAIL_DENY_LIST', default=('nobody@mozilla.org',))

# URL for Add-on Validation FAQ.
VALIDATION_FAQ_URL = ('https://wiki.mozilla.org/Add-ons/Reviewers/Guide/'
                      'AddonReviews#Step_2:_Automatic_validation')

SHIELD_STUDIES_SUPPORT_URL = 'https://support.mozilla.org/kb/shield'


# Celery
CELERY_BROKER_URL = env(
    'CELERY_BROKER_URL',
    default=os.environ.get(
        'CELERY_BROKER_URL', 'amqp://olympia:olympia@localhost:5672/olympia'))
CELERY_BROKER_CONNECTION_TIMEOUT = 0.1
CELERY_BROKER_HEARTBEAT = 60 * 15
CELERY_TASK_DEFAULT_QUEUE = 'default'
CELERY_RESULT_BACKEND = env(
    'CELERY_RESULT_BACKEND',
    default=os.environ.get(
        'CELERY_RESULT_BACKEND', 'redis://localhost:6379/1'))

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
    'olympia.lib.es.management.commands.reindex',
    'olympia.stats.management.commands.index_stats',
)

CELERY_TASK_QUEUES = (
    Queue('addons', routing_key='addons'),
    Queue('amo', routing_key='amo'),
    Queue('bandwagon', routing_key='bandwagon'),
    Queue('cron', routing_key='cron'),
    Queue('crypto', routing_key='crypto'),
    Queue('default', routing_key='default'),
    Queue('devhub', routing_key='devhub'),
    Queue('images', routing_key='images'),
    Queue('priority', routing_key='priority'),
    Queue('ratings', routing_key='ratings'),
    Queue('reviewers', routing_key='reviewers'),
    Queue('search', routing_key='search'),
    Queue('stats', routing_key='stats'),
    Queue('tags', routing_key='tags'),
    Queue('users', routing_key='users'),
    Queue('zadmin', routing_key='zadmin'),
)

# We have separate celeryds for processing devhub & images as fast as possible
# Some notes:
# - always add routes here instead of @task(queue=<name>)
# - when adding a queue, be sure to update deploy.py so that it gets restarted
CELERY_TASK_ROUTES = {
    # Priority.
    # If your tasks need to be run as soon as possible, add them here so they
    # are routed to the priority queue.
    'olympia.addons.tasks.index_addons': {'queue': 'priority'},
    'olympia.addons.tasks.unindex_addons': {'queue': 'priority'},
    'olympia.blocklist.tasks.process_blocklistsubmission': {
        'queue': 'priority'
    },
    'olympia.blocklist.tasks.import_block_from_blocklist': {
        'queue': 'priority'
    },
    'olympia.blocklist.tasks.delete_imported_block_from_blocklist': {
        'queue': 'priority'
    },
    'olympia.blocklist.tasks.upload_filter_to_kinto': {
        'queue': 'priority'
    },
    'olympia.versions.tasks.generate_static_theme_preview': {
        'queue': 'priority'
    },

    # Other queues we prioritize below.

    # 'Default' queue.
    'celery.accumulate': {'queue': 'default'},
    'celery.backend_cleanup': {'queue': 'default'},
    'celery.chain': {'queue': 'default'},
    'celery.chord': {'queue': 'default'},
    'celery.chunks': {'queue': 'default'},
    'celery.group': {'queue': 'default'},
    'celery.map': {'queue': 'default'},
    'celery.starmap': {'queue': 'default'},

    # AMO Devhub.
    'olympia.devhub.tasks.check_for_api_keys_in_file': {'queue': 'devhub'},
    'olympia.devhub.tasks.create_initial_validation_results': {
        'queue': 'devhub'
    },
    'olympia.devhub.tasks.forward_linter_results': {'queue': 'devhub'},
    'olympia.devhub.tasks.get_preview_sizes': {'queue': 'devhub'},
    'olympia.devhub.tasks.handle_file_validation_result': {'queue': 'devhub'},
    'olympia.devhub.tasks.handle_upload_validation_result': {
        'queue': 'devhub'
    },
    'olympia.devhub.tasks.revoke_api_key': {'queue': 'devhub'},
    'olympia.devhub.tasks.send_welcome_email': {'queue': 'devhub'},
    'olympia.devhub.tasks.submit_file': {'queue': 'devhub'},
    'olympia.devhub.tasks.validate_file': {'queue': 'devhub'},
    'olympia.devhub.tasks.validate_upload': {'queue': 'devhub'},
    'olympia.files.tasks.repack_fileupload': {'queue': 'devhub'},
    'olympia.scanners.tasks.run_customs': {'queue': 'devhub'},
    'olympia.scanners.tasks.run_wat': {'queue': 'devhub'},
    'olympia.scanners.tasks.run_yara': {'queue': 'devhub'},
    'olympia.scanners.tasks.call_mad_api': {'queue': 'devhub'},

    # Activity (goes to devhub queue).
    'olympia.activity.tasks.process_email': {'queue': 'devhub'},

    # This is currently used only by validation tasks.
    # This puts the chord_unlock task on the devhub queue. Which means anything
    # that uses chord() or group() must also be running in this queue or must
    # be on a worker that listens to the same queue.
    'celery.chord_unlock': {'queue': 'devhub'},

    # Images.
    'olympia.users.tasks.resize_photo': {'queue': 'images'},
    'olympia.devhub.tasks.recreate_previews': {'queue': 'images'},
    'olympia.devhub.tasks.resize_icon': {'queue': 'images'},
    'olympia.devhub.tasks.resize_preview': {'queue': 'images'},

    # AMO
    'olympia.amo.tasks.delete_anonymous_collections': {'queue': 'amo'},
    'olympia.amo.tasks.delete_logs': {'queue': 'amo'},
    'olympia.amo.tasks.send_email': {'queue': 'amo'},
    'olympia.amo.tasks.set_modified_on_object': {'queue': 'amo'},
    'olympia.amo.tasks.sync_object_to_basket': {'queue': 'amo'},

    # Addons
    'olympia.addons.tasks.add_dynamic_theme_tag': {'queue': 'addons'},
    'olympia.addons.tasks.delete_addons': {'queue': 'addons'},
    'olympia.addons.tasks.delete_preview_files': {'queue': 'addons'},
    'olympia.addons.tasks.migrate_webextensions_to_git_storage': {
        'queue': 'addons'
    },
    'olympia.addons.tasks.version_changed': {'queue': 'addons'},
    'olympia.files.tasks.extract_webext_permissions': {'queue': 'addons'},
    'olympia.files.tasks.hide_disabled_files': {'queue': 'addons'},
    'olympia.versions.tasks.delete_preview_files': {'queue': 'addons'},
    'olympia.versions.tasks.extract_version_to_git': {'queue': 'addons'},
    'olympia.git.tasks.continue_git_extraction': {'queue': 'addons'},
    'olympia.git.tasks.extract_versions_to_git': {'queue': 'addons'},
    'olympia.git.tasks.on_extraction_error': {'queue': 'addons'},
    'olympia.git.tasks.remove_git_extraction_entry': {'queue': 'addons'},
    # Additional image processing tasks that aren't as important go in the
    # addons queue to leave the 'devhub' queue free to process validations etc.
    'olympia.addons.tasks.extract_colors_from_static_themes': {
        'queue': 'addons'
    },
    'olympia.devhub.tasks.pngcrush_existing_preview': {'queue': 'addons'},
    'olympia.devhub.tasks.pngcrush_existing_icons': {'queue': 'addons'},
    'olympia.addons.tasks.recreate_theme_previews': {'queue': 'addons'},

    # Crons
    'olympia.addons.tasks.update_addon_average_daily_users': {'queue': 'cron'},
    'olympia.addons.tasks.update_addon_download_totals': {'queue': 'cron'},
    'olympia.addons.tasks.update_appsupport': {'queue': 'cron'},

    # Bandwagon
    'olympia.bandwagon.tasks.collection_meta': {'queue': 'bandwagon'},

    # Reviewers
    'olympia.reviewers.tasks.recalculate_post_review_weight': {
        'queue': 'reviewers'
    },

    # Crypto
    'olympia.lib.crypto.tasks.sign_addons': {'queue': 'crypto'},

    # Search
    'olympia.lib.es.management.commands.reindex.create_new_index': {
        'queue': 'search'
    },
    'olympia.lib.es.management.commands.reindex.delete_indexes': {
        'queue': 'search'
    },
    'olympia.lib.es.management.commands.reindex.flag_database': {
        'queue': 'search'
    },
    'olympia.lib.es.management.commands.reindex.unflag_database': {
        'queue': 'search'
    },
    'olympia.lib.es.management.commands.reindex.update_aliases': {
        'queue': 'search'
    },
    'olympia.addons.tasks.find_inconsistencies_between_es_and_db': {
        'queue': 'search'
    },

    # Ratings
    'olympia.ratings.tasks.addon_bayesian_rating': {'queue': 'ratings'},
    'olympia.ratings.tasks.addon_rating_aggregates': {'queue': 'ratings'},
    'olympia.ratings.tasks.update_denorm': {'queue': 'ratings'},

    # Stats
    'olympia.stats.tasks.index_download_counts': {'queue': 'stats'},
    'olympia.stats.tasks.index_update_counts': {'queue': 'stats'},

    # Tags
    'olympia.tags.tasks.update_all_tag_stats': {'queue': 'tags'},
    'olympia.tags.tasks.update_tag_stat': {'queue': 'tags'},

    # Users
    'olympia.accounts.tasks.primary_email_change_event': {'queue': 'users'},
    'olympia.users.tasks.delete_photo': {'queue': 'users'},
    'olympia.users.tasks.update_user_ratings_task': {'queue': 'users'},

    # Zadmin
    'olympia.scanners.tasks.run_yara_query_rule': {'queue': 'zadmin'},
    'olympia.scanners.tasks.run_yara_query_rule_on_versions_chunk': {
        'queue': 'zadmin'
    },
    'olympia.scanners.tasks.mark_yara_query_rule_as_completed_or_aborted': {
        'queue': 'zadmin'
    },
    'olympia.zadmin.tasks.celery_error': {'queue': 'zadmin'},
}

# See PEP 391 for formatting help.
LOGGING = {
    'version': 1,
    'filters': {},
    'formatters': {
        'json': {
            '()': olympia.core.logger.JsonFormatter,
            'logger_name': 'http_app_addons'
        },
    },
    'handlers': {
        'mozlog': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'json'
        },
        'null': {
            'class': 'logging.NullHandler',
        },
        'statsd': {
            'level': 'ERROR',
            'class': 'django_statsd.loggers.errors.StatsdHandler',
        },
    },
    'root': {'handlers': ['mozlog'], 'level': logging.INFO},
    'loggers': {
        'amo': {
            'handlers': ['mozlog'],
            'level': logging.DEBUG,
            'propagate': False
        },
        'amqp': {
            'handlers': ['null'],
            'level': logging.WARNING,
            'propagate': False
        },
        'caching': {
            'handlers': ['mozlog'],
            'level': logging.ERROR,
            'propagate': False
        },
        'caching.invalidation': {
            'handlers': ['null'],
            'level': logging.INFO,
            'propagate': False
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
            'propagate': True
        },
        'elasticsearch': {
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
        'newrelic': {
            'handlers': ['mozlog'],
            'level': logging.WARNING,
            'propagate': False,
        },
        'parso': {
            'handlers': ['null'],
            'level': logging.INFO,
            'propagate': False
        },
        'post_request_task': {
            'handlers': ['mozlog'],
            # Ignore INFO or DEBUG from post-request-task, it logs too much.
            'level': logging.WARNING,
            'propagate': False,
        },
        'raven': {
            'handlers': ['mozlog'],
            'level': logging.WARNING,
            'propagate': False
        },
        'rdflib': {
            'handlers': ['null'],
            'level': logging.INFO,
            'propagate': False,
        },
        'request': {
            'handlers': ['mozlog'],
            'level': logging.WARNING,
            'propagate': False
        },
        'request.summary': {
            'handlers': ['mozlog'],
            'level': logging.INFO,
            'propagate': False
        },
        's.client': {
            'handlers': ['mozlog'],
            'level': logging.INFO,
            'propagate': False
        },
        'z': {
            'handlers': ['mozlog'],
            'level': logging.INFO,
            'propagate': False
        },
        'z.addons': {
            'handlers': ['mozlog'],
            'level': logging.INFO,
            'propagate': False
        },
        'z.celery': {
            'handlers': ['statsd'],
            'level': logging.ERROR,
            'propagate': True,
        },
        'z.es': {
            'handlers': ['mozlog'],
            'level': logging.INFO,
            'propagate': False
        },
        'z.pool': {
            'handlers': ['mozlog'],
            'level': logging.ERROR,
            'propagate': False
        },
        'z.task': {
            'handlers': ['mozlog'],
            'level': logging.INFO,
            'propagate': False
        }
    },
}

# CSP Settings

PROD_CDN_HOST = 'https://addons.cdn.mozilla.net'
ANALYTICS_HOST = 'https://ssl.google-analytics.com'

CSP_REPORT_URI = '/__cspreport__'
CSP_REPORT_ONLY = False
CSP_EXCLUDE_URL_PREFIXES = ()

# NOTE: CSP_DEFAULT_SRC MUST be set otherwise things not set
# will default to being open to anything.
CSP_DEFAULT_SRC = (
    "'self'",
)
CSP_BASE_URI = (
    "'self'",
    # Required for the legacy discovery pane.
    'https://addons.mozilla.org',
)
CSP_CONNECT_SRC = (
    "'self'",
    'https://sentry.prod.mozaws.net',
    PROD_CDN_HOST,
)
CSP_FORM_ACTION = (
    "'self'",
    'https://developer.mozilla.org',
)
CSP_FONT_SRC = (
    "'self'",
    PROD_CDN_HOST,
)
CSP_CHILD_SRC = (
    "'self'",
    'https://www.google.com/recaptcha/',
    'https://www.recaptcha.net/recaptcha/',
)
CSP_FRAME_SRC = CSP_CHILD_SRC
CSP_IMG_SRC = (
    "'self'",
    'data:',  # Used in inlined mobile css.
    'blob:',  # Needed for image uploads.
    ANALYTICS_HOST,
    PROD_CDN_HOST,
    'https://static.addons.mozilla.net',  # CDN origin server.
    'https://sentry.prod.mozaws.net',
)
CSP_MEDIA_SRC = (
    'https://videos.cdn.mozilla.net',
)
CSP_OBJECT_SRC = ("'none'",)

CSP_SCRIPT_SRC = (
    'https://ssl.google-analytics.com/ga.js',
    'https://www.google.com/recaptcha/',
    'https://www.recaptcha.net/recaptcha/',
    'https://www.gstatic.com/recaptcha/',
    'https://www.gstatic.cn/recaptcha/',
    PROD_CDN_HOST,
)
CSP_STYLE_SRC = (
    "'self'",
    "'unsafe-inline'",
    PROD_CDN_HOST,
)

RESTRICTED_DOWNLOAD_CSP = {
    'DEFAULT_SRC': "'none'",
    'BASE_URI': "'none'",
    'FORM_ACTION': "'none'",
    'OBJECT_SRC': "'none'",
    'FRAME_ANCESTORS': "'none'",
    'REPORT_URI': CSP_REPORT_URI
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
MAX_ICON_UPLOAD_SIZE = 4 * 1024 * 1024
MAX_IMAGE_UPLOAD_SIZE = 4 * 1024 * 1024
MAX_VIDEO_UPLOAD_SIZE = 4 * 1024 * 1024
MAX_PHOTO_UPLOAD_SIZE = MAX_ICON_UPLOAD_SIZE
MAX_STATICTHEME_SIZE = 7 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_SIZE = 200 * 1024 * 1024

# File uploads should have -rw-r--r-- permissions in order to be served by
# nginx later one. The 0o prefix is intentional, this is an octal value.
FILE_UPLOAD_PERMISSIONS = 0o644

# RECAPTCHA: overload the following key settings in local_settings.py
# with your keys.
# Old recaptcha V1
RECAPTCHA_PUBLIC_KEY = env('RECAPTCHA_PUBLIC_KEY', default='')
RECAPTCHA_PRIVATE_KEY = env('RECAPTCHA_PRIVATE_KEY', default='')
# New Recaptcha V2
NOBOT_RECAPTCHA_PUBLIC_KEY = env('NOBOT_RECAPTCHA_PUBLIC_KEY', default='')
NOBOT_RECAPTCHA_PRIVATE_KEY = env('NOBOT_RECAPTCHA_PRIVATE_KEY', default='')

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

# The maximum file size that is shown inside the file viewer.
FILE_VIEWER_SIZE_LIMIT = 1048576

# The maximum file size that you can have inside a zip file.
FILE_UNZIP_SIZE_LIMIT = 104857600

# How long to delay tasks relying on file system to cope with NFS lag.
NFS_LAG_DELAY = 3

# Elasticsearch
ES_HOSTS = [os.environ.get('ELASTICSEARCH_LOCATION', '127.0.0.1:9200')]
ES_URLS = ['http://%s' % h for h in ES_HOSTS]
ES_INDEXES = {
    'default': 'addons',
    'stats': 'addons_stats',
}

ES_TIMEOUT = 30
ES_DEFAULT_NUM_REPLICAS = 2
ES_DEFAULT_NUM_SHARDS = 5

# Maximum result position. ES defaults to 10000 but we'd like more to make sure
# all our extensions can be found if searching without a query and
# paginating through all results.
# NOTE: This setting is being set during reindex, if this needs changing
# we need to trigger a reindex. It's also hard-coded in amo/pagination.py
# and there's a test verifying it's value is 25000 in amo/test_pagination.py
ES_MAX_RESULT_WINDOW = 25000

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

GRAPHITE_HOST = env('GRAPHITE_HOST', default='localhost')
GRAPHITE_PREFIX = env('GRAPHITE_PREFIX', default='amo')
GRAPHITE_PORT = 2003
GRAPHITE_TIMEOUT = 1

# IP addresses of servers we use as proxies.
KNOWN_PROXIES = []

# Blog URL
DEVELOPER_BLOG_URL = 'http://blog.mozilla.com/addons/feed/'

LOGIN_RATELIMIT_USER = 5
LOGIN_RATELIMIT_ALL_USERS = '15/m'

CSRF_FAILURE_VIEW = 'olympia.amo.views.csrf_failure'
CSRF_USE_SESSIONS = True

# Default file storage mechanism that holds media.
DEFAULT_FILE_STORAGE = 'olympia.amo.utils.LocalFileStorage'

# And how long we'll give the server to respond for monitoring.
# We currently do not have any actual timeouts during the signing-process.
SIGNING_SERVER_MONITORING_TIMEOUT = 10

AUTOGRAPH_CONFIG = {
    'server_url': env(
        'AUTOGRAPH_SERVER_URL',
        default='http://autograph:5500'),
    'user_id': env(
        'AUTOGRAPH_HAWK_USER_ID',
        default='alice'),
    'key': env(
        'AUTOGRAPH_HAWK_KEY',
        default='fs5wgcer9qj819kfptdlp8gm227ewxnzvsuj9ztycsx08hfhzu'),
    # This is configurable but we don't expect it to be set to anything else
    # but `webextensions-rsa` at this moment because AMO only accepts
    # regular add-ons, no system add-ons or extensions for example. These
    # are already signed when submitted to AMO.
    'signer': env(
        'AUTOGRAPH_SIGNER_ID',
        default='webextensions-rsa'),

    # This signer is only used for add-ons that are recommended.
    # The signer uses it's own HAWK auth credentials
    'recommendation_signer': env(
        'AUTOGRAPH_RECOMMENDATION_SIGNER_ID',
        default='webextensions-rsa-with-recommendation'),
    'recommendation_signer_user_id': env(
        'AUTOGRAPH_RECOMMENDATION_SIGNER_HAWK_USER_ID',
        default='bob'),
    'recommendation_signer_key': env(
        'AUTOGRAPH_RECOMMENDATION_SIGNER_HAWK_KEY',
        default='9vh6bhlc10y63ow2k4zke7k0c3l9hpr8mo96p92jmbfqngs9e7d'),

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
# The tuple is passed through to datetime.date, so please use a valid date
# tuple.
DEV_AGREEMENT_CHANGE_FALLBACK = datetime(2019, 12, 2, 12, 00)

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

# CDN Host is blank on local installs, overwritten in dev/stage/prod envs.
# Useful to force some dynamic content to be served from the CDN.
CDN_HOST = ''

# Static
STATIC_ROOT = path('site-static')
STATIC_URL = '/static/'

STATICFILES_DIRS = (
    path('static'),
)

# Path related settings. In dev/stage/prod `NETAPP_STORAGE_ROOT` environment
# variable will be set and point to our NFS/EFS storage
# Make sure to check overwrites in conftest.py if new settings are added
# or changed.
STORAGE_ROOT = env('NETAPP_STORAGE_ROOT', default=path('storage'))
ADDONS_PATH = os.path.join(STORAGE_ROOT, 'files')
GUARDED_ADDONS_PATH = os.path.join(STORAGE_ROOT, 'guarded-addons')
GIT_FILE_STORAGE_PATH = os.path.join(STORAGE_ROOT, 'git-storage')
MLBF_STORAGE_PATH = os.path.join(STORAGE_ROOT, 'mlbf')

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

# django-rest-framework-jwt settings:
JWT_AUTH = {
    # Use HMAC using SHA-256 hash algorithm. It should be the default, but we
    # want to make sure it does not change behind our backs.
    # See https://github.com/jpadilla/pyjwt/blob/master/docs/algorithms.rst
    'JWT_ALGORITHM': 'HS256',

    # This adds some padding to timestamp validation in case client/server
    # clocks are off.
    'JWT_LEEWAY': 5,

    # We don't allow refreshes.
    'JWT_ALLOW_REFRESH': False,
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
    ),
    'v4': (
        'l10n_flat_input_output',
        'addons-search-_score-field',
        'ratings-can_reply',
        'ratings-score-filter',
    ),
    'v5': (
        'addons-search-_score-field',
        'ratings-can_reply',
        'ratings-score-filter',
    ),
}

# Change this to deactivate API throttling for views using a throttling class
# depending on the one defined in olympia.api.throttling.
API_THROTTLING = True

REST_FRAMEWORK = {
    # Set this because the default is to also include:
    #   'rest_framework.renderers.BrowsableAPIRenderer'
    # Which it will try to use if the client accepts text/html.
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'olympia.api.authentication.WebTokenAuthentication',
    ),
    # Set parser classes to include the fix for
    # https://github.com/tomchristie/django-rest-framework/issues/3951
    'DEFAULT_PARSER_CLASSES': (
        'rest_framework.parsers.JSONParser',
        'rest_framework.parsers.FormParser',
        'olympia.api.parsers.MultiPartParser',
    ),

    'ALLOWED_VERSIONS': DRF_API_VERSIONS,
    'DEFAULT_VERSION': 'v4',
    'DEFAULT_VERSIONING_CLASS': (
        'rest_framework.versioning.NamespaceVersioning'),

    # Add our custom exception handler, that wraps all exceptions into
    # Responses and not just the ones that are api-related.
    'EXCEPTION_HANDLER': 'olympia.api.exceptions.custom_exception_handler',

    # Enable pagination
    'PAGE_SIZE': 25,
    # Use our pagination class by default, which allows clients to request a
    # different page size.
    'DEFAULT_PAGINATION_CLASS': (
        'olympia.api.pagination.CustomPageNumberPagination'),

    # Use json by default when using APIClient.
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',

    # Use http://ecma-international.org/ecma-262/5.1/#sec-15.9.1.15
    # We can't use the default because we don't use django timezone support.
    'DATETIME_FORMAT': '%Y-%m-%dT%H:%M:%SZ',

    # Set our default ordering parameter
    'ORDERING_PARAM': 'sort',
}


def get_raven_release():
    version_json = os.path.join(ROOT, 'version.json')
    version = None

    if os.path.exists(version_json):
        try:
            with open(version_json, 'r') as fobj:
                contents = fobj.read()
                data = json.loads(contents)
                version = data.get('version') or data.get('commit')
        except (IOError, KeyError):
            version = None

    if not version or version == 'origin/master':
        try:
            version = raven.fetch_git_sha(ROOT)
        except raven.exceptions.InvalidGitRepository:
            version = None
    return version


# This is the DSN to the Sentry service.
RAVEN_CONFIG = {
    'dsn': env('SENTRY_DSN', default=os.environ.get('SENTRY_DSN')),
    # Automatically configure the release based on git information.
    # This uses our `version.json` file if possible or tries to fetch
    # the current git-sha.
    'release': get_raven_release(),
}

# Automatically do 'from olympia import amo' when running shell_plus.
SHELL_PLUS_POST_IMPORTS = (
    ('olympia', 'amo'),
)

FXA_CONTENT_HOST = 'https://accounts.firefox.com'
FXA_OAUTH_HOST = 'https://oauth.accounts.firefox.com/v1'
FXA_PROFILE_HOST = 'https://profile.accounts.firefox.com/v1'
DEFAULT_FXA_CONFIG_NAME = 'default'
ALLOWED_FXA_CONFIGS = ['default']

# List all jobs that should be callable with cron here.
# syntax is: job_and_method_name: full.package.path
CRON_JOBS = {
    'update_addon_average_daily_users': 'olympia.addons.cron',
    'update_addon_download_totals': 'olympia.addons.cron',
    'addon_last_updated': 'olympia.addons.cron',
    'update_addon_appsupport': 'olympia.addons.cron',
    'hide_disabled_files': 'olympia.addons.cron',
    'unhide_disabled_files': 'olympia.addons.cron',
    'deliver_hotness': 'olympia.addons.cron',

    'gc': 'olympia.amo.cron',
    'category_totals': 'olympia.amo.cron',
    'weekly_downloads': 'olympia.amo.cron',

    'auto_import_blocklist': 'olympia.blocklist.cron',
    'upload_mlbf_to_kinto': 'olympia.blocklist.cron',

    'update_blog_posts': 'olympia.devhub.cron',

    'cleanup_extracted_file': 'olympia.files.cron',
    'cleanup_validation_results': 'olympia.files.cron',

    'index_latest_stats': 'olympia.stats.cron',

    'update_user_ratings': 'olympia.users.cron',
}

RECOMMENDATION_ENGINE_URL = env(
    'RECOMMENDATION_ENGINE_URL',
    default='https://taar.dev.mozaws.net/v1/api/recommendations/')
TAAR_LITE_RECOMMENDATION_ENGINE_URL = env(
    'TAAR_LITE_RECOMMENDATION_ENGINE_URL',
    default=('https://taar.dev.mozaws.net/taarlite/api/v1/'
             'addon_recommendations/'))
RECOMMENDATION_ENGINE_TIMEOUT = env.float(
    'RECOMMENDATION_ENGINE_TIMEOUT', default=1)

# Reputation service is disabled by default, enabled for dev/stage/prod via
# those 3 env variables.
REPUTATION_SERVICE_URL = env('REPUTATION_SERVICE_URL', default=None)
REPUTATION_SERVICE_TOKEN = env('REPUTATION_SERVICE_TOKEN', default=None)
REPUTATION_SERVICE_TIMEOUT = env.float('REPUTATION_SERVICE_TIMEOUT', default=1)

# This is the queue used for addons-dev, so it'll consume events (i.e. process
# then delete) before you can locally.  If you really need to test get ops to
# stop the 'monitor_fxa_sqs` command.
FXA_SQS_AWS_QUEUE_URL = (
    'https://sqs.us-east-1.amazonaws.com/927034868273/'
    'amo-account-change-dev')
FXA_SQS_AWS_WAIT_TIME = 20  # Seconds.

AWS_STATS_S3_BUCKET = env('AWS_STATS_S3_BUCKET', default=None)
AWS_STATS_S3_PREFIX = env('AWS_STATS_S3_PREFIX', default='amo_stats')

MIGRATED_LWT_UPDATES_ENABLED = True

BASKET_URL = env('BASKET_URL', default='https://basket.allizom.org')
BASKET_API_KEY = env('BASKET_API_KEY', default=None)
# Default is 10, the API usually answers in 0.5 - 1.5 seconds.
BASKET_TIMEOUT = 5
MOZILLA_NEWLETTER_URL = env(
    'MOZILLA_NEWSLETTER_URL',
    default='https://www.mozilla.org/en-US/newsletter/')

GEOIP_PATH = '/usr/local/share/GeoIP/GeoLite2-Country.mmdb'

EXTENSION_WORKSHOP_URL = env(
    'EXTENSION_WORKSHOP_URL',
    default='https://extensionworkshop-dev.allizom.org')

# Sectools
SCANNER_TIMEOUT = 60  # seconds
CUSTOMS_API_URL = env('CUSTOMS_API_URL', default=None)
CUSTOMS_API_KEY = env('CUSTOMS_API_KEY', default=None)
WAT_API_URL = env('WAT_API_URL', default=None)
WAT_API_KEY = env('WAT_API_KEY', default=None)
MAD_API_URL = env('MAD_API_URL', default=None)
MAD_API_TIMEOUT = 5  # seconds
# Git(Hub) repository names, e.g., `owner/repo-name`
CUSTOMS_GIT_REPOSITORY = env('CUSTOMS_GIT_REPOSITORY', default=None)
YARA_GIT_REPOSITORY = env('YARA_GIT_REPOSITORY', default=None)

# Addon.average_daily_user count that forces dual sign-off for Blocklist Blocks
DUAL_SIGNOFF_AVERAGE_DAILY_USERS_THRESHOLD = 100_000
REMOTE_SETTINGS_API_URL = 'https://kinto.dev.mozaws.net/v1/'
REMOTE_SETTINGS_WRITER_URL = 'https://kinto.dev.mozaws.net/v1/'
REMOTE_SETTINGS_WRITER_BUCKET = 'blocklists'

# The kinto test server needs accounts and setting up before using.
KINTO_API_IS_TEST_SERVER = False
BLOCKLIST_KINTO_USERNAME = env(
    'BLOCKLIST_KINTO_USERNAME', default='amo_dev')
BLOCKLIST_KINTO_PASSWORD = env(
    'BLOCKLIST_KINTO_PASSWORD', default='amo_dev_password')

# The path to the current google service account configuration. This is
# being used to query Google BigQuery as part of our stats processing.
# If this is `None` we're going to use service mocks for testing
GOOGLE_APPLICATION_CREDENTIALS = env(
    'GOOGLE_APPLICATION_CREDENTIALS', default=None)
