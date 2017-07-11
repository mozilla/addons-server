# -*- coding: utf-8 -*-
# Django settings for addons-server project.

import logging
import os
import socket

from django.utils.functional import lazy
from django.core.urlresolvers import reverse_lazy

import environ
from kombu import Queue


env = environ.Env()

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
    # CACHE_PREFIX.  This will let us not have to flush memcache during updates
    # and it will let us preload data into it before a production push.
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


# We need to track this because hudson can't just call its checkout "olympia".
# It puts it in a dir called "workspace".  Way to be, hudson.
ROOT_PACKAGE = os.path.basename(ROOT)

DEBUG = True
DEBUG_PROPAGATE_EXCEPTIONS = True
SILENCED_SYSTEM_CHECKS = (
    # Recommendation to use OneToOneField instead of ForeignKey(unique=True)
    # but our translations are the way they are...
    'fields.W342',
)

# LESS CSS OPTIONS (Debug only).
LESS_PREPROCESS = True  # Compile LESS with Node, rather than client-side JS?
LESS_LIVE_REFRESH = False  # Refresh the CSS on save?
LESS_BIN = 'lessc'

# Path to stylus (to compile .styl files).
STYLUS_BIN = 'stylus'

# Path to cleancss (our CSS minifier).
CLEANCSS_BIN = 'cleancss'

# Path to uglifyjs (our JS minifier).
UGLIFY_BIN = 'uglifyjs'  # Set as None to use YUI instead (at your risk).

FLIGTAR = 'amo-admins+fligtar-rip@mozilla.org'
EDITORS_EMAIL = 'amo-editors@mozilla.org'
SENIOR_EDITORS_EMAIL = 'amo-editors+somethingbad@mozilla.org'
THEMES_EMAIL = 'theme-reviews@mozilla.org'
ABUSE_EMAIL = 'amo-admins+ivebeenabused@mozilla.org'
NOBODY_EMAIL = 'nobody@mozilla.org'

# Add Access-Control-Allow-Origin: * header for the new API with
# django-cors-headers.
CORS_ORIGIN_ALLOW_ALL = True
CORS_URLS_REGEX = r'^/api/v3/.*$'


# Sadly the term WHITELIST is used by the library
# https://pypi.python.org/pypi/django-cors-headers-multi/1.2.0
# TODO(andym): see if I can get them to accept a patch for that.
def cors_endpoint_overrides(internal, public):
    return [
        (r'^/api/v3/internal/accounts/login/?$', {
            'CORS_ORIGIN_ALLOW_ALL': False,
            'CORS_ORIGIN_WHITELIST': internal,
            'CORS_ALLOW_CREDENTIALS': True,
        }),
        (r'^/api/v3/accounts/login/?$', {
            'CORS_ORIGIN_ALLOW_ALL': False,
            'CORS_ORIGIN_WHITELIST': public,
            'CORS_ALLOW_CREDENTIALS': True,
        }),
        (r'^/api/v3/internal/.*$', {
            'CORS_ORIGIN_ALLOW_ALL': False,
            'CORS_ORIGIN_WHITELIST': internal,
        }),
    ]


CORS_ENDPOINT_OVERRIDES = cors_endpoint_overrides(
    public=['localhost:3000', 'olympia.dev'],
    internal=['localhost:3000'],
)

DATABASES = {
    'default': env.db(default='mysql://root:@localhost/olympia')
}
DATABASES['default']['OPTIONS'] = {'sql_mode': 'STRICT_ALL_TABLES'}
DATABASES['default']['TEST_CHARSET'] = 'utf8'
DATABASES['default']['TEST_COLLATION'] = 'utf8_general_ci'
# Run all views in a transaction unless they are decorated not to.
DATABASES['default']['ATOMIC_REQUESTS'] = True
# Pool our database connections up for 300 seconds
DATABASES['default']['CONN_MAX_AGE'] = 300

# A database to be used by the services scripts, which does not use Django.
# The settings can be copied from DATABASES, but since its not a full Django
# database connection, only some values are supported.
SERVICES_DATABASE = {
    'NAME': DATABASES['default']['NAME'],
    'USER': DATABASES['default']['USER'],
    'PASSWORD': DATABASES['default']['PASSWORD'],
    'HOST': DATABASES['default']['HOST'],
    'PORT': DATABASES['default']['PORT'],
}

DATABASE_ROUTERS = ('multidb.PinningMasterSlaveRouter',)

# Put the aliases for your slave databases in this list.
SLAVE_DATABASES = []

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# If running in a Windows environment this must be set to the same as your
# system time zone.
TIME_ZONE = 'UTC'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-US'

# Accepted locales
# Note: If you update this list, don't forget to also update the locale
# permissions in the database.
AMO_LANGUAGES = (
    'af', 'ar', 'bg', 'bn-BD', 'ca', 'cs', 'da', 'de', 'dsb',
    'el', 'en-GB', 'en-US', 'es', 'eu', 'fa', 'fi', 'fr', 'ga-IE', 'he', 'hu',
    'hsb', 'id', 'it', 'ja', 'ka', 'kab', 'ko', 'nn-NO', 'mk', 'mn', 'nl',
    'pl', 'pt-BR', 'pt-PT', 'ro', 'ru', 'sk', 'sl', 'sq', 'sv-SE', 'uk', 'vi',
    'zh-CN', 'zh-TW',
)

# Explicit conversion of a shorter language code into a more specific one.
SHORTER_LANGUAGES = {
    'en': 'en-US', 'ga': 'ga-IE', 'pt': 'pt-PT', 'sv': 'sv-SE', 'zh': 'zh-CN'
}

# Not shown on the site, but .po files exist and these are available on the
# L10n dashboard.  Generally languages start here and move into AMO_LANGUAGES.
HIDDEN_LANGUAGES = ('cy', 'hr', 'sr', 'sr-Latn', 'tr')

DEBUG_LANGUAGES = ('dbr', 'dbl')


def lazy_langs(languages):
    from product_details import product_details
    if not product_details.languages:
        return {}

    language_mapping = {}

    for lang in languages:
        if lang == 'dbl':
            lang_name = product_details.languages['dbg']['native']
        elif lang == 'dbr':
            lang_name = product_details.languages['dbg']['native'] + ' (RTL)'
        else:
            lang_name = product_details.languages[lang]['native']

        language_mapping[lang.lower()] = lang_name

    return language_mapping


# Where product details are stored see django-mozilla-product-details
PROD_DETAILS_DIR = path('src', 'olympia', 'lib', 'product_json')
PROD_DETAILS_STORAGE = 'olympia.lib.product_details_backend.NoCachePDFileStorage'  # noqa

# Override Django's built-in with our native names
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
LANGUAGES_BIDI = ('ar', 'fa', 'fa-IR', 'he', 'dbr')

LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])

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

# Domain of the services site.  This is where your API, and in-product pages
# live.
SERVICES_DOMAIN = 'services.%s' % DOMAIN

# Full URL to your API service. No trailing slash.
#   Example: https://services.addons.mozilla.org
SERVICES_URL = 'http://%s' % SERVICES_DOMAIN

# Filter IP addresses of allowed clients that can post email through the API.
ALLOWED_CLIENTS_EMAIL_API = env.list('ALLOWED_CLIENTS_EMAIL_API', default=[])
# Auth token required to authorize inbound email.
INBOUND_EMAIL_SECRET_KEY = env('INBOUND_EMAIL_SECRET_KEY', default='')
# Validation key we need to send in POST response.
INBOUND_EMAIL_VALIDATION_KEY = env('INBOUND_EMAIL_VALIDATION_KEY', default='')
# Domain emails should be sent to.
INBOUND_EMAIL_DOMAIN = env('INBOUND_EMAIL_DOMAIN', default=DOMAIN)

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = path('user-media')

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = '/user-media/'

# Absolute path to a temporary storage area
TMP_PATH = path('tmp')

# Tarballs in DUMPED_APPS_PATH deleted 30 days after they have been written.
DUMPED_APPS_DAYS_DELETE = 3600 * 24 * 30

# Tarballs in DUMPED_USERS_PATH deleted 30 days after they have been written.
DUMPED_USERS_DAYS_DELETE = 3600 * 24 * 30

# path that isn't just one /, and doesn't require any locale or app.
SUPPORTED_NONAPPS_NONLOCALES_PREFIX = (
    'api/v3',
)

# paths that don't require an app prefix
# This needs to be kept in sync with addons-frontend's
# validClientAppUrlExceptions
# https://github.com/mozilla/addons-frontend/blob/master/config/default-amo.js
SUPPORTED_NONAPPS = (
    'about', 'admin', 'apps', 'contribute.json', 'credits',
    'developer_agreement', 'developer_faq', 'developers', 'editors', 'faq',
    'jsi18n', 'review_guide', 'google1f3e37b7351799a5.html',
    'robots.txt', 'statistics', 'services', 'sunbird', 'static', 'user-media',
    '__version__',
)
DEFAULT_APP = 'firefox'

# paths that don't require a locale prefix
# This needs to be kept in sync with addons-frontend's validLocaleUrlExceptions
# https://github.com/mozilla/addons-frontend/blob/master/config/default-amo.js
SUPPORTED_NONLOCALES = (
    'contribute.json', 'google1f3e37b7351799a5.html', 'robots.txt', 'services',
    'downloads', 'static', 'user-media', '__version__',
)

# Make this unique, and don't share it with anybody.
SECRET_KEY = 'this-is-a-dummy-key-and-its-overridden-for-prod-servers'

# Templates
JINJA_EXCLUDE_TEMPLATE_PATHS = (
    r'^admin\/',
    r'^users\/email',
    r'^reviews\/emails',
    r'^editors\/emails',
    r'^amo\/emails',
    r'^devhub\/email\/revoked-key-email.ltxt',
    r'^devhub\/email\/new-key-email.ltxt',

    # Django specific templates
    r'^registration\/password_reset_subject.txt'
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
                'session_csrf.context_processor',

                'django.contrib.messages.context_processors.messages',

                'olympia.amo.context_processors.app',
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
                'olympia.amo.ext.cache',
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
                'session_csrf.context_processor',

                'django.contrib.messages.context_processors.messages',
            ),
        }
    },
]


X_FRAME_OPTIONS = 'DENY'
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000

MIDDLEWARE_CLASSES = (
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

    'olympia.amo.middleware.CommonMiddleware',
    'olympia.amo.middleware.NoVarySessionMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'olympia.amo.middleware.AuthenticationMiddlewareWithoutAPI',
    'olympia.search.middleware.ElasticsearchExceptionMiddleware',
    'session_csrf.CsrfMiddleware',

    # This should come after AuthenticationMiddlewareWithoutAPI (to get the
    # current user) and after SetRemoteAddrFromForwardedFor (to get the correct
    # IP).
    'olympia.access.middleware.UserAndAddrMiddleware',

    'olympia.amo.middleware.ScrubRequestOnException',
)

# Auth
AUTH_USER_MODEL = 'users.UserProfile'

# Override this in the site settings.
ROOT_URLCONF = 'olympia.urls'

INSTALLED_APPS = (
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
    'olympia.browse',
    'olympia.compat',
    'olympia.devhub',
    'olympia.discovery',
    'olympia.editors',
    'olympia.files',
    'olympia.github',
    'olympia.internal_tools',
    'olympia.legacy_api',
    'olympia.legacy_discovery',
    'olympia.lib.es',
    'olympia.pages',
    'olympia.reviews',
    'olympia.search',
    'olympia.stats',
    'olympia.tags',
    'olympia.users',
    'olympia.versions',
    'olympia.zadmin',

    # Third party apps
    'product_details',
    'csp',
    'aesfield',
    'django_extensions',
    'raven.contrib.django',
    'rest_framework',
    'waffle',
    'jingo_minify',
    'django_jinja',
    'puente',

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

# These apps are only needed in a testing environment. They are added to
# INSTALLED_APPS by settings_test.py (which is itself loaded by setup.cfg by
# py.test)
TEST_INSTALLED_APPS = (
    'olympia.translations.tests.testapp',
)

# Tells the extract script what files to look for l10n in and what function
# handles the extraction. The puente library expects this.
PUENTE = {
    'BASE_DIR': ROOT,
    # Tells the extract script what files to look for l10n in and what function
    # handles the extraction.
    'DOMAIN_METHODS': {
        'django': [
            ('src/olympia/**.py', 'python'),

            # Make sure we're parsing django-admin templates with the django
            # template extractor
            (
                'src/olympia/zadmin/templates/admin/*.html',
                'django_babel.extract.extract_django'
            ),

            ('src/olympia/**/templates/**.html', 'jinja2'),
            ('**/templates/**.lhtml', 'jinja2'),
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
            'css/legacy/autocomplete.css',
            'css/zamboni/zamboni.css',
            'css/zamboni/tags.css',
            'css/zamboni/tabs.css',
            'css/impala/formset.less',
            'css/impala/suggestions.less',
            'css/impala/header.less',
            'css/impala/moz-tab.css',
            'css/impala/footer.less',
            'css/impala/faux-zamboni.less',
            'css/zamboni/themes.less',
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
            'css/impala/reviews.less',
            'css/impala/buttons.less',
            'css/impala/promos.less',
            'css/impala/addon_details.less',
            'css/impala/policy.less',
            'css/impala/expando.less',
            'css/impala/popups.less',
            'css/impala/l10n.less',
            'css/impala/contributions.less',
            'css/impala/lightbox.less',
            'css/impala/prose.less',
            'css/impala/abuse.less',
            'css/impala/paginator.less',
            'css/impala/listing.less',
            'css/impala/versions.less',
            'css/impala/users.less',
            'css/impala/collections.less',
            'css/impala/tooltips.less',
            'css/impala/search.less',
            'css/impala/suggestions.less',
            'css/node_lib/jquery.minicolors.css',
            'css/impala/personas.less',
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
            'css/zamboni/discovery-pane.css',
            'css/impala/promos.less',
            'css/legacy/jquery-lightbox.css',
        ),
        'zamboni/devhub': (
            'css/impala/tooltips.less',
            'css/zamboni/developers.css',
            'css/zamboni/docs.less',
            'css/impala/developers.less',
            'css/impala/personas.less',
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
        'zamboni/editors': (
            'css/zamboni/editors.styl',
            'css/zamboni/unlisted.less',
        ),
        'zamboni/themes_review': (
            'css/zamboni/developers.css',
            'css/zamboni/editors.styl',
            'css/zamboni/themes_review.styl',
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
        # JS files common to the entire site (pre-impala).
        'common': (
            'js/node_lib/raven.js',
            'js/common/raven-config.js',
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
            'js/zamboni/global.js',
            'js/amo2009/global.js',
            'js/common/ratingwidget.js',
            'js/node_lib/jqModal.js',
            'js/zamboni/l10n.js',
            'js/zamboni/debouncer.js',

            # Homepage
            'js/impala/promos.js',
            'js/zamboni/homepage.js',

            # Add-ons details page
            'js/lib/ui.lightbox.js',
            'js/zamboni/contributions.js',
            'js/zamboni/addon_details.js',
            'js/impala/abuse.js',
            'js/zamboni/reviews.js',

            # Personas
            'js/lib/jquery.hoverIntent.js',
            'js/zamboni/personas_core.js',
            'js/zamboni/personas.js',

            # Unicode: needs to be loaded after collections.js which listens to
            # an event fired in this file.
            'js/zamboni/unicode.js',

            # Collections
            'js/zamboni/collections.js',

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
            'js/node_lib/raven.js',
            'js/common/raven-config.js',
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
            'js/zamboni/global.js',
            'js/impala/global.js',
            'js/common/ratingwidget.js',
            'js/node_lib/jqModal.js',
            'js/zamboni/l10n.js',
            'js/impala/forms.js',

            # Homepage
            'js/impala/promos.js',
            'js/impala/homepage.js',

            # Add-ons details page
            'js/lib/ui.lightbox.js',
            'js/zamboni/contributions.js',
            'js/impala/addon_details.js',
            'js/impala/abuse.js',
            'js/impala/reviews.js',

            # Browse listing pages
            'js/impala/listing.js',

            # Personas
            'js/lib/jquery.hoverIntent.js',
            'js/zamboni/personas_core.js',
            'js/zamboni/personas.js',

            # Persona creation
            'js/common/upload-image.js',
            'js/node_lib/jquery.minicolors.js',
            'js/impala/persona_creation.js',

            # Unicode: needs to be loaded after collections.js which listens to
            # an event fired in this file.
            'js/zamboni/unicode.js',

            # Collections
            'js/zamboni/collections.js',
            'js/impala/collections.js',

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

            # Personas
            'js/lib/jquery.hoverIntent.js',
            'js/zamboni/personas_core.js',
            'js/zamboni/personas.js',

            'js/zamboni/debouncer.js',
            'js/lib/truncate.js',
            'js/zamboni/truncation.js',

            'js/impala/promos.js',
            'js/zamboni/discovery_addons.js',
            'js/zamboni/discovery_pane.js',
        ),
        'zamboni/discovery-video': (
            'js/lib/popcorn-1.0.js',
            'js/zamboni/discovery_video.js',
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
        ),
        'zamboni/editors': (
            'js/lib/highcharts.src.js',
            'js/zamboni/editors.js',
            'js/lib/jquery.hoverIntent.js',  # Used by jquery.zoomBox.
            'js/lib/jquery.zoomBox.js',  # Used by themes_review.
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


# Caching
# Prefix for cache keys (will prevent collisions when running parallel copies)
CACHE_PREFIX = 'amo:%s:' % build_id
KEY_PREFIX = CACHE_PREFIX
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
CA_CERT_BUNDLE_PATH = os.path.join(
    ROOT, 'src/olympia/amo/certificates/roots.pem')

# URL paths
# paths for images, e.g. mozcdn.com/amo or '/static'
VAMO_URL = 'https://versioncheck.addons.mozilla.org'
NEW_PERSONAS_UPDATE_URL = VAMO_URL + '/%(locale)s/themes/update-check/%(id)d'


# Outgoing URL bouncer
REDIRECT_URL = 'https://outgoing.prod.mozaws.net/v1/'
REDIRECT_SECRET_KEY = ''

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
LOGIN_URL = reverse_lazy('users.login')
LOGOUT_URL = reverse_lazy('users.logout')
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
# When logging in with browser ID, a username is created automatically.
# In the case of duplicates, the process is recursive up to this number
# of times.
MAX_GEN_USERNAME_TRIES = 50

# PayPal Settings
PAYPAL_API_VERSION = '78'
PAYPAL_APP_ID = ''

# URLs for various calls.
PAYPAL_API_URL = 'https://api-3t.paypal.com/nvp'
PAYPAL_CGI_URL = 'https://www.paypal.com/cgi-bin/webscr'
PAYPAL_PAY_URL = 'https://svcs.paypal.com/AdaptivePayments/'
PAYPAL_FLOW_URL = 'https://paypal.com/webapps/adaptivepayment/flow/pay'
PAYPAL_PERMISSIONS_URL = 'https://svcs.paypal.com/Permissions/'
PAYPAL_JS_URL = 'https://www.paypalobjects.com/js/external/dg.js'

# Permissions for the live or sandbox servers
PAYPAL_EMBEDDED_AUTH = {'USER': '', 'PASSWORD': '', 'SIGNATURE': ''}

# The PayPal cert that we'll use for checking.
# When None, the Mozilla CA bundle is used to look it up.
PAYPAL_CERT = None

# Contribution limit, one time and monthly
MAX_CONTRIBUTION = 1000

# Email settings
ADDONS_EMAIL = "Mozilla Add-ons <nobody@mozilla.org>"
DEFAULT_FROM_EMAIL = ADDONS_EMAIL

# Email goes to the console by default.  s/console/smtp/ for regular delivery
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Please use all lowercase for the deny_list.
EMAIL_DENY_LIST = (
    'nobody@mozilla.org',
)

# Please use all lowercase for the QA allow list.
EMAIL_QA_ALLOW_LIST = ()

# URL for Add-on Validation FAQ.
VALIDATION_FAQ_URL = ('https://wiki.mozilla.org/Add-ons/Reviewers/Guide/'
                      'AddonReviews#Step_2:_Automatic_validation')


# Celery
BROKER_URL = os.environ.get('BROKER_URL',
                            'amqp://olympia:olympia@localhost:5672/olympia')
BROKER_CONNECTION_TIMEOUT = 0.1
BROKER_HEARTBEAT = 60 * 15
CELERY_DEFAULT_QUEUE = 'default'
CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND',
                                       'redis://localhost:6379/1')

CELERY_IGNORE_RESULT = True
CELERY_SEND_TASK_ERROR_EMAILS = True
CELERYD_HIJACK_ROOT_LOGGER = False
CELERY_IMPORTS = (
    'olympia.lib.crypto.tasks',
    'olympia.lib.es.management.commands.reindex',
)

CELERY_QUEUES = (
    Queue('default', routing_key='default'),
    Queue('priority', routing_key='priority'),
    Queue('devhub', routing_key='devhub'),
    Queue('images', routing_key='images'),
    Queue('limited', routing_key='limited'),
    Queue('amo', routing_key='amo'),
    Queue('addons', routing_key='addons'),
    Queue('api', routing_key='api'),
    Queue('cron', routing_key='cron'),
    Queue('bandwagon', routing_key='bandwagon'),
    Queue('editors', routing_key='editors'),
    Queue('crypto', routing_key='crypto'),
    Queue('search', routing_key='search'),
    Queue('reviews', routing_key='reviews'),
    Queue('stats', routing_key='stats'),
    Queue('tags', routing_key='tags'),
    Queue('users', routing_key='users'),
    Queue('zadmin', routing_key='zadmin'),
)

# We have separate celeryds for processing devhub & images as fast as possible
# Some notes:
# - always add routes here instead of @task(queue=<name>)
# - when adding a queue, be sure to update deploy.py so that it gets restarted
CELERY_ROUTES = {
    # Priority.
    # If your tasks need to be run as soon as possible, add them here so they
    # are routed to the priority queue.
    'olympia.addons.tasks.index_addons': {'queue': 'priority'},
    'olympia.addons.tasks.unindex_addons': {'queue': 'priority'},
    'olympia.addons.tasks.save_theme': {'queue': 'priority'},
    'olympia.addons.tasks.save_theme_reupload': {'queue': 'priority'},
    'olympia.bandwagon.tasks.index_collections': {'queue': 'priority'},
    'olympia.bandwagon.tasks.unindex_collections': {'queue': 'priority'},
    'olympia.users.tasks.index_users': {'queue': 'priority'},
    'olympia.users.tasks.unindex_users': {'queue': 'priority'},

    # Other queues we prioritize below.

    # AMO Devhub.
    'olympia.devhub.tasks.convert_purified': {'queue': 'devhub'},
    'olympia.devhub.tasks.get_preview_sizes': {'queue': 'devhub'},
    'olympia.devhub.tasks.handle_file_validation_result': {'queue': 'devhub'},
    'olympia.devhub.tasks.handle_upload_validation_result': {
        'queue': 'devhub'},
    'olympia.devhub.tasks.send_welcome_email': {'queue': 'devhub'},
    'olympia.devhub.tasks.submit_file': {'queue': 'devhub'},
    'olympia.devhub.tasks.validate_file': {'queue': 'devhub'},
    'olympia.devhub.tasks.validate_file_path': {'queue': 'devhub'},

    # Activity (goes to devhub queue).
    'olympia.activity.tasks.process_email': {'queue': 'devhub'},

    # This is currently used only by validation tasks.
    # This puts the chord_unlock task on the devhub queue. Which means anything
    # that uses chord() or group() must also be running in this queue or must
    # be on a worker that listens to the same queue.
    'celery.chord_unlock': {'queue': 'devhub'},
    'olympia.devhub.tasks.compatibility_check': {'queue': 'devhub'},

    # Images.
    'olympia.bandwagon.tasks.resize_icon': {'queue': 'images'},
    'olympia.users.tasks.resize_photo': {'queue': 'images'},
    'olympia.devhub.tasks.resize_icon': {'queue': 'images'},
    'olympia.devhub.tasks.resize_preview': {'queue': 'images'},

    # AMO validator.
    'olympia.zadmin.tasks.bulk_validate_file': {'queue': 'limited'},

    # AMO
    'olympia.amo.tasks.delete_anonymous_collections': {'queue': 'amo'},
    'olympia.amo.tasks.delete_logs': {'queue': 'amo'},
    'olympia.amo.tasks.delete_stale_contributions': {'queue': 'amo'},
    'olympia.amo.tasks.send_email': {'queue': 'amo'},
    'olympia.amo.tasks.set_modified_on_object': {'queue': 'amo'},

    # Addons
    'olympia.addons.tasks.calc_checksum': {'queue': 'addons'},
    'olympia.addons.tasks.delete_persona_image': {'queue': 'addons'},
    'olympia.addons.tasks.delete_preview_files': {'queue': 'addons'},
    'olympia.addons.tasks.update_incompatible_appversions': {
        'queue': 'addons'},
    'olympia.addons.tasks.version_changed': {'queue': 'addons'},

    # API
    'olympia.api.tasks.process_results': {'queue': 'api'},
    'olympia.api.tasks.process_webhook': {'queue': 'api'},

    # Crons
    'olympia.addons.cron._update_addon_average_daily_users': {'queue': 'cron'},
    'olympia.addons.cron._update_addon_download_totals': {'queue': 'cron'},
    'olympia.addons.cron._update_addons_current_version': {'queue': 'cron'},
    'olympia.addons.cron._update_appsupport': {'queue': 'cron'},
    'olympia.addons.cron._update_daily_theme_user_counts': {'queue': 'cron'},
    'olympia.bandwagon.cron._drop_collection_recs': {'queue': 'cron'},
    'olympia.bandwagon.cron._update_collections_subscribers': {
        'queue': 'cron'},
    'olympia.bandwagon.cron._update_collections_votes': {'queue': 'cron'},

    # Bandwagon
    'olympia.bandwagon.tasks.collection_meta': {'queue': 'bandwagon'},
    'olympia.bandwagon.tasks.collection_votes': {'queue': 'bandwagon'},
    'olympia.bandwagon.tasks.collection_watchers': {'queue': 'bandwagon'},
    'olympia.bandwagon.tasks.delete_icon': {'queue': 'bandwagon'},

    # Editors
    'olympia.editors.tasks.add_commentlog': {'queue': 'editors'},
    'olympia.editors.tasks.add_versionlog': {'queue': 'editors'},
    'olympia.editors.tasks.approve_rereview': {'queue': 'editors'},
    'olympia.editors.tasks.reject_rereview': {'queue': 'editors'},
    'olympia.editors.tasks.send_mail': {'queue': 'editors'},

    # Crypto
    'olympia.lib.crypto.tasks.sign_addons': {'queue': 'crypto'},

    # Search
    'olympia.lib.es.management.commands.reindex.create_new_index': {
        'queue': 'search'},
    'olympia.lib.es.management.commands.reindex.delete_indexes': {
        'queue': 'search'},
    'olympia.lib.es.management.commands.reindex.flag_database': {
        'queue': 'search'},
    'olympia.lib.es.management.commands.reindex.index_data': {
        'queue': 'search'},
    'olympia.lib.es.management.commands.reindex.unflag_database': {
        'queue': 'search'},
    'olympia.lib.es.management.commands.reindex.update_aliases': {
        'queue': 'search'},

    # Reviews
    'olympia.reviews.tasks.addon_bayesian_rating': {'queue': 'reviews'},
    'olympia.reviews.tasks.addon_grouped_rating': {'queue': 'reviews'},
    'olympia.reviews.tasks.addon_review_aggregates': {'queue': 'reviews'},
    'olympia.reviews.tasks.update_denorm': {'queue': 'reviews'},


    # Stats
    'olympia.stats.tasks.index_collection_counts': {'queue': 'stats'},
    'olympia.stats.tasks.index_download_counts': {'queue': 'stats'},
    'olympia.stats.tasks.index_theme_user_counts': {'queue': 'stats'},
    'olympia.stats.tasks.index_update_counts': {'queue': 'stats'},
    'olympia.stats.tasks.update_addons_collections_downloads': {
        'queue': 'stats'},
    'olympia.stats.tasks.update_collections_total': {'queue': 'stats'},
    'olympia.stats.tasks.update_global_totals': {'queue': 'stats'},
    'olympia.stats.tasks.update_google_analytics': {'queue': 'stats'},

    # Tags
    'olympia.tags.tasks.update_all_tag_stats': {'queue': 'tags'},
    'olympia.tags.tasks.update_tag_stat': {'queue': 'tags'},

    # Users
    'olympia.users.tasks.delete_photo': {'queue': 'users'},
    'olympia.users.tasks.update_user_ratings_task': {'queue': 'users'},
    'olympia.users.tasks.generate_secret_for_users': {'queue': 'users'},

    # Zadmin
    'olympia.zadmin.tasks.add_validation_jobs': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.admin_email': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.celery_error': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.fetch_langpack': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.fetch_langpacks': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.notify_compatibility': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.notify_compatibility_chunk': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.update_maxversions': {'queue': 'zadmin'},

    # Github API
    'olympia.github.tasks.process_results': {'queue': 'devhub'},
    'olympia.github.tasks.process_webhook': {'queue': 'devhub'},
}


# This is just a place to store these values, you apply them in your
# task decorator, for example:
#   @task(time_limit=CELERY_TIME_LIMITS['lib...']['hard'])
# Otherwise your task will use the default settings.
CELERY_TIME_LIMITS = {
    # The reindex management command can take up to 3 hours to run.
    'olympia.lib.es.management.commands.reindex': {
        'soft': 10800, 'hard': 14400},
}

# When testing, we always want tasks to raise exceptions. Good for sanity.
CELERY_EAGER_PROPAGATES_EXCEPTIONS = True

# Time in seconds before celery.exceptions.SoftTimeLimitExceeded is raised.
# The task can catch that and recover but should exit ASAP. Note that there is
# a separate, shorter timeout for validation tasks.
CELERYD_TASK_SOFT_TIME_LIMIT = 60 * 30

# Logging
LOG_LEVEL = logging.DEBUG
USE_SYSLOG = True
USE_MOZLOG = True
SYSLOG_TAG = "http_app_addons"
SYSLOG_TAG2 = "http_app_addons2"
MOZLOG_NAME = SYSLOG_TAG
# See PEP 391 and log_settings_base.py for formatting help.  Each section of
# LOGGING will get merged into the corresponding section of
# log_settings_base.py. Handlers and log levels are set up automatically based
# on LOG_LEVEL and DEBUG unless you set them here.  Messages will not
# propagate through a logger unless propagate: True is set.
LOGGING_CONFIG = None
LOGGING = {
    'loggers': {
        'amo.validator': {'level': logging.WARNING},
        'amqplib': {'handlers': ['null']},
        'caching.invalidation': {'handlers': ['null']},
        'caching': {'level': logging.ERROR},
        'elasticsearch': {'handlers': ['null']},
        'rdflib': {'handlers': ['null']},
        'z.task': {'level': logging.INFO},
        'z.es': {'level': logging.INFO},
        'z.editors.auto_approve': {'handlers': ['syslog', 'console']},
        's.client': {'level': logging.INFO},
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
    'https://ic.paypal.com',
    'https://paypal.com',
    'https://www.google.com/recaptcha/',
    'https://www.paypal.com',
)
CSP_FRAME_SRC = CSP_CHILD_SRC
CSP_IMG_SRC = (
    "'self'",
    'data:',  # Used in inlined mobile css.
    'blob:',  # Needed for image uploads.
    'https://www.paypal.com/webapps/checkout/',  # Needed for contrib.
    'https://www.paypal.com/webapps/hermes/api/logger',  # Needed for contrib.
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
    'https://www.gstatic.com/recaptcha/',
    PAYPAL_JS_URL,
    PROD_CDN_HOST,
)
CSP_STYLE_SRC = (
    "'self'",
    "'unsafe-inline'",
    PROD_CDN_HOST,
)

# Should robots.txt deny everything or disallow a calculated list of URLs we
# don't want to be crawled?  Default is true, allow everything, toggled to
# False on -dev and stage.
# Also see http://www.google.com/support/webmasters/bin/answer.py?answer=93710
ENGAGE_ROBOTS = True

# Read-only mode setup.
READ_ONLY = False


# Turn on read-only mode in local_settings.py by putting this line
# at the VERY BOTTOM: read_only_mode(globals())
def read_only_mode(env):
    env['READ_ONLY'] = True

    # Replace the default (master) db with a slave connection.
    if not env.get('SLAVE_DATABASES'):
        raise Exception("We need at least one slave database.")
    slave = env['SLAVE_DATABASES'][0]
    env['DATABASES']['default'] = env['DATABASES'][slave]

    # No sessions without the database, so disable auth.
    env['AUTHENTICATION_BACKENDS'] = ('olympia.users.backends.NoAuthForYou',)

    # Add in the read-only middleware before csrf middleware.
    extra = 'olympia.amo.middleware.ReadOnlyMiddleware'
    before = 'session_csrf.CsrfMiddleware'
    m = list(env['MIDDLEWARE_CLASSES'])
    m.insert(m.index(before), extra)
    env['MIDDLEWARE_CLASSES'] = tuple(m)


# Uploaded file limits
MAX_ICON_UPLOAD_SIZE = 4 * 1024 * 1024
MAX_IMAGE_UPLOAD_SIZE = 4 * 1024 * 1024
MAX_VIDEO_UPLOAD_SIZE = 4 * 1024 * 1024
MAX_PHOTO_UPLOAD_SIZE = MAX_ICON_UPLOAD_SIZE
MAX_PERSONA_UPLOAD_SIZE = 300 * 1024
MAX_REVIEW_ATTACHMENT_UPLOAD_SIZE = 5 * 1024 * 1024

# RECAPTCHA: overload the following key settings in local_settings.py
# with your keys.
NOBOT_RECAPTCHA_PUBLIC_KEY = ''
NOBOT_RECAPTCHA_PRIVATE_KEY = ''

# Send Django signals asynchronously on a background thread.
ASYNC_SIGNALS = True

# Performance for persona pagination, we hardcode the number of
# available pages when the filter is up-and-coming.
PERSONA_DEFAULT_PAGES = 10

REDIS_LOCATION = os.environ.get(
    'REDIS_LOCATION',
    'redis://localhost:6379/0?socket_timeout=0.5')


def get_redis_settings(uri):
    import urlparse
    urlparse.uses_netloc.append('redis')

    result = urlparse.urlparse(uri)

    options = dict(urlparse.parse_qsl(result.query))

    if 'socket_timeout' in options:
        options['socket_timeout'] = float(options['socket_timeout'])

    return {
        'HOST': result.hostname,
        'PORT': result.port,
        'PASSWORD': result.password,
        'DB': int((result.path or '0').lstrip('/')),
        'OPTIONS': options
    }


# This is used for `django-cache-machine`
REDIS_BACKEND = REDIS_LOCATION

REDIS_BACKENDS = {
    'master': get_redis_settings(REDIS_LOCATION)
}

# Number of seconds before celery tasks will abort addon validation:
VALIDATOR_TIMEOUT = 110

# Max number of warnings/errors to show from validator. Set to None for no
# limit.
VALIDATOR_MESSAGE_LIMIT = 500

# Feature flags
UNLINK_SITE_STATS = True

# Set to True if we're allowed to use X-SENDFILE.
XSENDFILE = True
XSENDFILE_HEADER = 'X-SENDFILE'

MOBILE_COOKIE = 'mamo'

DEFAULT_SUGGESTED_CONTRIBUTION = 5

# Path to `ps`.
PS_BIN = '/bin/ps'

# The maximum file size that is shown inside the file viewer.
FILE_VIEWER_SIZE_LIMIT = 1048576
# The maximum file size that you can have inside a zip file.
FILE_UNZIP_SIZE_LIMIT = 104857600

# How long to delay tasks relying on file system to cope with NFS lag.
NFS_LAG_DELAY = 3

# An approved list of domains that the authentication script will redirect to
# upon successfully logging in or out.
VALID_LOGIN_REDIRECTS = {
    'builder': 'https://builder.addons.mozilla.org',
    'builderstage': 'https://builder-addons.allizom.org',
    'buildertrunk': 'https://builder-addons-dev.allizom.org',
}

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

# Default AMO user id to use for tasks.
TASK_USER_ID = 4757633

# If this is False, tasks and other jobs that send non-critical emails should
# use a fake email backend.
SEND_REAL_EMAIL = False

STATSD_HOST = 'localhost'
STATSD_PORT = 8125
STATSD_PREFIX = 'amo'

# The django statsd client to use, see django-statsd for more.
STATSD_CLIENT = 'django_statsd.clients.normal'

GRAPHITE_HOST = 'localhost'
GRAPHITE_PORT = 2003
GRAPHITE_PREFIX = 'amo'
GRAPHITE_TIMEOUT = 1

# IP addresses of servers we use as proxies.
KNOWN_PROXIES = []

# Blog URL
DEVELOPER_BLOG_URL = 'http://blog.mozilla.com/addons/feed/'

LOGIN_RATELIMIT_USER = 5
LOGIN_RATELIMIT_ALL_USERS = '15/m'

CSRF_FAILURE_VIEW = 'olympia.amo.views.csrf_failure'

# Testing responsiveness without rate limits.
CELERY_DISABLE_RATE_LIMITS = True

# Default file storage mechanism that holds media.
DEFAULT_FILE_STORAGE = 'olympia.amo.utils.LocalFileStorage'

# This is the signing server for signing files.
SIGNING_SERVER = ''
# And how long we'll give the server to respond.
SIGNING_SERVER_TIMEOUT = 10
# Hotfix addons (don't sign those, they're already signed by Mozilla.
HOTFIX_ADDON_GUIDS = ['firefox-hotfix@mozilla.org',
                      'thunderbird-hotfix@mozilla.org']
# Minimum Firefox version for default to compatible addons to be signed.
MIN_D2C_VERSION = '4'
# Minimum Firefox version for not default to compatible addons to be signed.
MIN_NOT_D2C_VERSION = '37'

# True when the Django app is running from the test suite.
IN_TEST_SUITE = False

# Temporary flag to work with navigator.mozPay() on devices that don't
# support it natively.
SIMULATE_NAV_PAY = False

# When the dev. agreement gets updated and you need users to re-accept it
# change this date. You won't want to do this for minor format changes.
# The tuple is passed through to datetime.date, so please use a valid date
# tuple. If the value is None, then it will just not be used at all.
DEV_AGREEMENT_LAST_UPDATED = None

# If you want to allow self-reviews for add-ons/apps, then enable this.
# In production we do not want to allow this.
ALLOW_SELF_REVIEWS = False

# Credentials for accessing Google Analytics stats.
GOOGLE_ANALYTICS_CREDENTIALS = {}

# Which domain to access GA stats for. If not set, defaults to DOMAIN.
GOOGLE_ANALYTICS_DOMAIN = None

# Language pack fetcher settings
LANGPACK_OWNER_EMAIL = 'addons-team@mozilla.com'
LANGPACK_DOWNLOAD_BASE = 'https://ftp.mozilla.org/pub/mozilla.org/'
LANGPACK_PATH_DEFAULT = '%s/releases/%s/win32/xpi/'
# E.g. https://ftp.mozilla.org/pub/mozilla.org/firefox/releases/23.0/SHA512SUMS
LANGPACK_MANIFEST_PATH = '../../SHA512SUMS'
LANGPACK_MAX_SIZE = 5 * 1024 * 1024  # 5MB should be more than enough

# This saves us when we upgrade jingo-minify (jsocol/jingo-minify@916b054c).
JINGO_MINIFY_USE_STATIC = True

# Whitelist IP addresses of the allowed clients that can post email
# through the API.
ALLOWED_CLIENTS_EMAIL_API = []

# Allow URL style format override. eg. "?format=json"
URL_FORMAT_OVERRIDE = 'format'

# Add on used to collect stats (!technical dept around!)
ADDON_COLLECTOR_ID = 11950

# Connection to the hive server.
HIVE_CONNECTION = {
    'host': 'peach-gw.peach.metrics.scl3.mozilla.com',
    'port': 10000,
    'user': 'amo_prod',
    'password': '',
    'auth_mechanism': 'PLAIN',
}

# Enable ETags (based on response content) on every view in CommonMiddleware.
USE_ETAGS = True

# CDN Host is blank on local installs, overwritten in dev/stage/prod envs.
# Useful to force some dynamic content to be served from the CDN.
CDN_HOST = ''

# Static
STATIC_ROOT = path('site-static')
STATIC_URL = '/static/'
JINGO_MINIFY_ROOT = path('static')
STATICFILES_DIRS = (
    path('static'),
    JINGO_MINIFY_ROOT
)
NETAPP_STORAGE = TMP_PATH
GUARDED_ADDONS_PATH = ROOT + '/guarded-addons'


# These are key files that must be present on disk to encrypt/decrypt certain
# database fields.
AES_KEYS = {
    # 'api_key:secret': os.path.join(ROOT, 'path', 'to', 'file.key'),
}

# Time in seconds for how long a JWT auth token created by developers with
# their API key can live. When developers are creating auth tokens they cannot
# set the expiration any longer than this.
MAX_APIKEY_JWT_AUTH_TOKEN_LIFETIME = 5 * 60

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
    # Add our custom exception handler, that wraps all exceptions into
    # Responses and not just the ones that are api-related.
    'EXCEPTION_HANDLER': 'olympia.api.exceptions.custom_exception_handler',

    # Enable pagination
    'PAGE_SIZE': 25,

    # Use our pagination class by default, which allows clients to request a
    # different page size.
    'DEFAULT_PAGINATION_CLASS': (
        'olympia.api.paginator.CustomPageNumberPagination'),

    # Use json by default when using APIClient.
    'TEST_REQUEST_DEFAULT_FORMAT': 'json',

    # Use http://ecma-international.org/ecma-262/5.1/#sec-15.9.1.15
    # We can't use the default because we don't use django timezone support.
    'DATETIME_FORMAT': '%Y-%m-%dT%H:%M:%SZ',

    # Set our default ordering parameter
    'ORDERING_PARAM': 'sort',
}

# This is the DSN to the local Sentry service. It might be overridden in
# site-specific settings files as well.
SENTRY_DSN = os.environ.get('SENTRY_DSN')

# Automatically do 'from olympia import amo' when running shell_plus.
SHELL_PLUS_POST_IMPORTS = (
    ('olympia', 'amo'),
)

DEFAULT_FXA_CONFIG_NAME = 'default'
INTERNAL_FXA_CONFIG_NAME = 'internal'
ALLOWED_FXA_CONFIGS = ['default']

WEBEXT_PERM_DESCRIPTIONS_URL = (
    'https://hg.mozilla.org/mozilla-central/raw-file/tip/'
    'browser/locales/en-US/chrome/browser/browser.properties')
WEBEXT_PERM_DESCRIPTIONS_LOCALISED_URL = (
    'https://hg.mozilla.org/l10n-central/{locale}/raw-file/tip/'
    'browser/chrome/browser/browser.properties')

# List all jobs that should be callable with cron here.
# syntax is: job_and_method_name: full.package.path
CRON_JOBS = {
    'update_addon_average_daily_users': 'olympia.addons.cron',
    'update_addon_download_totals': 'olympia.addons.cron',
    'addon_last_updated': 'olympia.addons.cron',
    'update_addon_appsupport': 'olympia.addons.cron',
    'update_all_appsupport': 'olympia.addons.cron',
    'hide_disabled_files': 'olympia.addons.cron',
    'unhide_disabled_files': 'olympia.addons.cron',
    'deliver_hotness': 'olympia.addons.cron',
    'reindex_addons': 'olympia.addons.cron',
    'cleanup_image_files': 'olympia.addons.cron',

    'gc': 'olympia.amo.cron',
    'category_totals': 'olympia.amo.cron',
    'collection_subscribers': 'olympia.amo.cron',
    'weekly_downloads': 'olympia.amo.cron',

    'update_collections_subscribers': 'olympia.bandwagon.cron',
    'update_collections_votes': 'olympia.bandwagon.cron',
    'reindex_collections': 'olympia.bandwagon.cron',

    'compatibility_report': 'olympia.compat.cron',

    'update_blog_posts': 'olympia.devhub.cron',

    'cleanup_extracted_file': 'olympia.files.cron',
    'cleanup_validation_results': 'olympia.files.cron',

    'update_addons_collections_downloads': 'olympia.stats.cron',
    'update_collections_total': 'olympia.stats.cron',
    'update_global_totals': 'olympia.stats.cron',
    'update_google_analytics': 'olympia.stats.cron',
    'index_latest_stats': 'olympia.stats.cron',

    'update_user_ratings': 'olympia.users.cron',
    'reindex_users': 'olympia.users.cron',
}
