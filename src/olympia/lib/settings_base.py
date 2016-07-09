# -*- coding: utf-8 -*-
# Django settings for olympia project.

import datetime
import logging
import os
import socket

from django.utils.functional import lazy
from django.core.urlresolvers import reverse_lazy

import environ

env = environ.Env()

ALLOWED_HOSTS = [
    '.allizom.org',
    '.mozilla.org',
    '.mozilla.com',
    '.mozilla.net',
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
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = True

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
INTERNAL_DOMAINS = ['localhost:3000']
CORS_ENDPOINT_OVERRIDES = [
    (r'^/api/v3/internal/accounts/login/?$', {
        'CORS_ORIGIN_ALLOW_ALL': False,
        'CORS_ORIGIN_WHITELIST': INTERNAL_DOMAINS,
        'CORS_ALLOW_CREDENTIALS': True,
    }),
    (r'^/api/v3/internal/.*$', {
        'CORS_ORIGIN_ALLOW_ALL': False,
        'CORS_ORIGIN_WHITELIST': INTERNAL_DOMAINS,
    }),
]

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

PASSWORD_HASHERS = (
    'olympia.users.models.SHA512PasswordHasher',
)

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
    'hsb', 'id', 'it', 'ja', 'ka', 'ko', 'nn-NO', 'mk', 'mn', 'nl', 'pl',
    'pt-BR', 'pt-PT', 'ro', 'ru', 'sk', 'sl', 'sq', 'sv-SE', 'uk', 'vi',
    'zh-CN', 'zh-TW',
)

# Explicit conversion of a shorter language code into a more specific one.
SHORTER_LANGUAGES = {
    'en': 'en-US', 'ga': 'ga-IE', 'pt': 'pt-PT', 'sv': 'sv-SE', 'zh': 'zh-CN'
}

# Not shown on the site, but .po files exist and these are available on the
# L10n dashboard.  Generally languages start here and move into AMO_LANGUAGES.
HIDDEN_LANGUAGES = ('cy', 'hr', 'sr', 'sr-Latn', 'tr')


def lazy_langs(languages):
    from product_details import product_details
    if not product_details.languages:
        return {}
    return dict([(i.lower(), product_details.languages[i]['native'])
                 for i in languages])

# Where product details are stored see django-mozilla-product-details
PROD_DETAILS_DIR = path('src', 'olympia', 'lib', 'product_json')
PROD_DETAILS_URL = 'https://svn.mozilla.org/libs/product-details/json/'
PROD_DETAILS_STORAGE = 'olympia.lib.product_details_backend.NoCachePDFileStorage'  # noqa

# Override Django's built-in with our native names
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
RTL_LANGUAGES = ('ar', 'fa', 'fa-IR', 'he')

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

# The domain of the mobile site.
MOBILE_DOMAIN = 'm.%s' % DOMAIN

# The full url of the mobile site.
MOBILE_SITE_URL = 'http://%s' % MOBILE_DOMAIN

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
    'blocked/blocklists.json',
)

# paths that don't require an app prefix
SUPPORTED_NONAPPS = (
    'about', 'admin', 'apps', 'blocklist', 'contribute.json', 'credits',
    'developer_agreement', 'developer_faq', 'developers', 'editors', 'faq',
    'jsi18n', 'review_guide', 'google1f3e37b7351799a5.html',
    'robots.txt', 'statistics', 'services', 'sunbird', 'static', 'user-media',
    '__version__',
)
DEFAULT_APP = 'firefox'

# paths that don't require a locale prefix
SUPPORTED_NONLOCALES = (
    'contribute.json', 'google1f3e37b7351799a5.html', 'robots.txt', 'services',
    'downloads', 'blocklist', 'static', 'user-media', '__version__',
)

# Make this unique, and don't share it with anybody.
SECRET_KEY = 'this-is-a-dummy-key-and-its-overridden-for-prod-servers'

# Templates

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'olympia.lib.template_loader.Loader',
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
)

# We don't want jingo's template loaded to pick up templates for third party
# apps that don't use Jinja2. The Following is a list of prefixes for jingo to
# ignore.
JINGO_EXCLUDE_APPS = (
    'django_extensions',
    'admin',
    'toolbar_statsd',
    'registration',
    'rest_framework',
    'waffle',
)

JINGO_EXCLUDE_PATHS = (
    'users/email',
    'reviews/emails',
    'editors/emails',
    'amo/emails',
    'devhub/email/revoked-key-email.ltxt',
    'devhub/email/new-key-email.ltxt'
)

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.contrib.auth.context_processors.auth',
    'django.core.context_processors.debug',
    'django.core.context_processors.media',
    'django.core.context_processors.request',
    'session_csrf.context_processor',

    'django.contrib.messages.context_processors.messages',

    'olympia.amo.context_processors.app',
    'olympia.amo.context_processors.i18n',
    'olympia.amo.context_processors.global_settings',
    'olympia.amo.context_processors.static_url',
    'jingo_minify.helpers.build_ids',
)

TEMPLATE_DIRS = (
    path('media', 'docs'),
    path('src/olympia/templates'),
)


def JINJA_CONFIG():
    import jinja2
    from django.conf import settings
    from django.core.cache import cache
    config = {
        'extensions': [
            'olympia.amo.ext.cache',
            'puente.ext.i18n',
            'waffle.jinja.WaffleExtension',
            'jinja2.ext.do',
            'jinja2.ext.with_',
            'jinja2.ext.loopcontrols'
        ],
        'finalize': lambda x: x if x is not None else '',
        'autoescape': True,
    }

    if False and not settings.DEBUG:
        # We're passing the _cache object directly to jinja because
        # Django can't store binary directly; it enforces unicode on it.
        # Details: http://jinja.pocoo.org/2/documentation/api#bytecode-cache
        # and in the errors you get when you try it the other way.
        bc = jinja2.MemcachedBytecodeCache(cache._cache,
                                           "%sj2:" % settings.CACHE_PREFIX)
        config['cache_size'] = -1  # Never clear the cache
        config['bytecode_cache'] = bc
    return config


MIDDLEWARE_CLASSES = (
    # AMO URL middleware comes first so everyone else sees nice URLs.
    'django_statsd.middleware.GraphiteRequestTimingMiddleware',
    'django_statsd.middleware.GraphiteMiddleware',
    'olympia.amo.middleware.LocaleAndAppURLMiddleware',
    # Mobile detection should happen in Zeus.
    'mobility.middleware.DetectMobileMiddleware',
    'mobility.middleware.XMobileMiddleware',
    'olympia.amo.middleware.RemoveSlashMiddleware',

    # Munging REMOTE_ADDR must come before ThreadRequest.
    'commonware.middleware.SetRemoteAddrFromForwardedFor',

    'commonware.middleware.FrameOptionsHeader',
    'commonware.middleware.XSSProtectionHeader',
    'commonware.middleware.ContentTypeOptionsHeader',
    'commonware.middleware.StrictTransportMiddleware',
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
    'commonware.log.ThreadRequestMiddleware',
    'olympia.search.middleware.ElasticsearchExceptionMiddleware',
    'session_csrf.CsrfMiddleware',

    # This should come after authentication middleware
    'olympia.access.middleware.ACLMiddleware',

    'commonware.middleware.ScrubRequestOnException',
)

# Auth
AUTHENTICATION_BACKENDS = (
    'olympia.users.backends.AmoUserBackend',
)
AUTH_USER_MODEL = 'users.UserProfile'

# Override this in the site settings.
ROOT_URLCONF = 'olympia.urls'

INSTALLED_APPS = (
    'olympia.core',
    'olympia.amo',  # amo comes first so it always takes precedence.
    'olympia.abuse',
    'olympia.access',
    'olympia.accounts',
    'olympia.addons',
    'olympia.api',
    'olympia.applications',
    'olympia.bandwagon',
    'olympia.blocklist',
    'olympia.browse',
    'olympia.compat',
    'olympia.devhub',
    'olympia.discovery',
    'olympia.editors',
    'olympia.files',
    'olympia.internal_tools',
    'olympia.legacy_api',
    'olympia.legacy_discovery',
    'olympia.lib.es',
    'olympia.pages',
    'olympia.reviews',
    'olympia.search',
    'olympia.stats',
    'olympia.tags',
    'olympia.translations',
    'olympia.users',
    'olympia.versions',
    'olympia.zadmin',

    # Third party apps
    'product_details',
    'cronjobs',
    'csp',
    'aesfield',
    'django_extensions',
    'raven.contrib.django',
    'rest_framework',
    'waffle',
    'jingo_minify',
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
            'css/impala/jquery.minicolors.css',
            'css/impala/personas.less',
            'css/impala/login.less',
            'css/impala/dictionaries.less',
            'css/impala/apps.less',
            'css/impala/formset.less',
            'css/impala/tables.less',
            'css/impala/compat.less',
            'css/impala/fxa-migration.less',
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
        'zamboni/mobile': (
            'css/zamboni/mobile.css',
            'css/mobile/typography.less',
            'css/mobile/forms.less',
            'css/mobile/header.less',
            'css/mobile/search.less',
            'css/mobile/listing.less',
            'css/mobile/footer.less',
            'css/impala/fxa-migration.less',
            'css/mobile/notifications.less',
        ),
        'zamboni/admin': (
            'css/zamboni/admin-django.css',
            'css/zamboni/admin-mozilla.css',
            'css/zamboni/admin_features.css',
            # Datepicker styles and jQuery UI core.
            'css/zamboni/jquery-ui/custom-1.7.2.css',
        ),
    },
    'js': {
        # JS files common to the entire site (pre-impala).
        'common': (
            'js/lib/raven.min.js',
            'js/common/raven-config.js',
            'js/lib/underscore.js',
            'js/zamboni/browser.js',
            'js/amo2009/addons.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/lib/format.js',
            'js/lib/jquery.cookie.js',
            'js/zamboni/storage.js',
            'js/zamboni/buttons.js',
            'js/zamboni/tabs.js',
            'js/common/keys.js',

            # jQuery UI
            'js/lib/jquery-ui/core.js',
            'js/lib/jquery-ui/position.js',
            'js/lib/jquery-ui/widget.js',
            'js/lib/jquery-ui/menu.js',
            'js/lib/jquery-ui/mouse.js',
            'js/lib/jquery-ui/autocomplete.js',
            'js/lib/jquery-ui/datepicker.js',
            'js/lib/jquery-ui/sortable.js',

            'js/zamboni/helpers.js',
            'js/zamboni/global.js',
            'js/amo2009/global.js',
            'js/common/ratingwidget.js',
            'js/lib/jquery-ui/jqModal.js',
            'js/zamboni/l10n.js',
            'js/zamboni/debouncer.js',

            # Homepage
            'js/impala/promos.js',
            'js/zamboni/homepage.js',

            # Add-ons details page
            'js/lib/jquery-ui/ui.lightbox.js',
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

            # Password length and strength
            'js/zamboni/password-strength.js',

            # Search suggestions
            'js/impala/forms.js',
            'js/impala/ajaxcache.js',
            'js/impala/suggestions.js',
            'js/impala/site_suggestions.js',
        ),

        # Impala and Legacy: Things to be loaded at the top of the page
        'preload': (
            'js/lib/jquery-1.12.0.js',
            'js/lib/jquery.browser.js',
            'js/impala/preloaded.js',
            'js/zamboni/analytics.js',
        ),
        # Impala: Things to be loaded at the bottom
        'impala': (
            'js/lib/raven.min.js',
            'js/common/raven-config.js',
            'js/lib/underscore.js',
            'js/impala/carousel.js',
            'js/zamboni/browser.js',
            'js/amo2009/addons.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/lib/format.js',
            'js/lib/jquery.cookie.js',
            'js/zamboni/storage.js',
            'js/zamboni/buttons.js',
            'js/lib/jquery.pjax.js',
            'js/impala/footer.js',
            'js/common/keys.js',

            # jQuery UI
            'js/lib/jquery-ui/core.js',
            'js/lib/jquery-ui/position.js',
            'js/lib/jquery-ui/widget.js',
            'js/lib/jquery-ui/mouse.js',
            'js/lib/jquery-ui/menu.js',
            'js/lib/jquery-ui/autocomplete.js',
            'js/lib/jquery-ui/datepicker.js',
            'js/lib/jquery-ui/sortable.js',

            # Firefox Accounts
            'js/lib/uri.js',
            'js/common/fxa-login.js',

            'js/lib/truncate.js',
            'js/zamboni/truncation.js',
            'js/impala/ajaxcache.js',
            'js/zamboni/helpers.js',
            'js/zamboni/global.js',
            'js/impala/global.js',
            'js/common/ratingwidget.js',
            'js/lib/jquery-ui/jqModal.js',
            'js/zamboni/l10n.js',
            'js/impala/forms.js',

            # Homepage
            'js/impala/promos.js',
            'js/impala/homepage.js',

            # Add-ons details page
            'js/lib/jquery-ui/ui.lightbox.js',
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
            'js/lib/jquery.minicolors.js',
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
            'js/lib/jquery-1.12.0.js',
            'js/lib/jquery.browser.js',
            'js/lib/underscore.js',
            'js/zamboni/browser.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/lib/format.js',
            'js/impala/carousel.js',
            'js/zamboni/analytics.js',

            # Add-ons details
            'js/lib/jquery.cookie.js',
            'js/zamboni/storage.js',
            'js/zamboni/buttons.js',
            'js/lib/jquery-ui/ui.lightbox.js',

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
            'js/lib/syntaxhighlighter/xregexp-min.js',
            'js/lib/syntaxhighlighter/shCore.js',
            'js/lib/syntaxhighlighter/shLegacy.js',
            'js/lib/syntaxhighlighter/shBrushAppleScript.js',
            'js/lib/syntaxhighlighter/shBrushAS3.js',
            'js/lib/syntaxhighlighter/shBrushBash.js',
            'js/lib/syntaxhighlighter/shBrushCpp.js',
            'js/lib/syntaxhighlighter/shBrushCSharp.js',
            'js/lib/syntaxhighlighter/shBrushCss.js',
            'js/lib/syntaxhighlighter/shBrushDiff.js',
            'js/lib/syntaxhighlighter/shBrushJava.js',
            'js/lib/syntaxhighlighter/shBrushJScript.js',
            'js/lib/syntaxhighlighter/shBrushPhp.js',
            'js/lib/syntaxhighlighter/shBrushPlain.js',
            'js/lib/syntaxhighlighter/shBrushPython.js',
            'js/lib/syntaxhighlighter/shBrushSass.js',
            'js/lib/syntaxhighlighter/shBrushSql.js',
            'js/lib/syntaxhighlighter/shBrushVb.js',
            'js/lib/syntaxhighlighter/shBrushXml.js',
            'js/zamboni/storage.js',
            'js/zamboni/files_templates.js',
            'js/zamboni/files.js',
        ),
        'zamboni/mobile': (
            'js/lib/jquery-1.12.0.js',
            'js/lib/jquery.browser.js',
            'js/lib/underscore.js',
            'js/lib/jqmobile.js',
            'js/lib/jquery.cookie.js',
            'js/zamboni/browser.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/zamboni/analytics.js',
            'js/lib/format.js',
            'js/zamboni/mobile/buttons.js',
            'js/lib/truncate.js',
            'js/zamboni/truncation.js',
            'js/impala/footer.js',
            'js/zamboni/personas_core.js',
            'js/zamboni/mobile/personas.js',
            'js/zamboni/helpers.js',
            'js/zamboni/mobile/general.js',
            'js/common/ratingwidget.js',

            # Firefox Accounts
            'js/lib/uri.js',
            'js/common/fxa-login.js',
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
            'js/lib/less.js',
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

# Add-on download settings.
PRIVATE_MIRROR_URL = '/_privatefiles'

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
REDIRECT_URL_WHITELIST = ['addons.mozilla.org']

# Default to short expiration; check "remember me" to override
SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'
# See: https://github.com/mozilla/addons-server/issues/1789
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 2592000
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

# Please use all lowercase for the blacklist.
EMAIL_BLACKLIST = (
    'nobody@mozilla.org',
)

# Please use all lowercase for the QA whitelist.
EMAIL_QA_WHITELIST = ()

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
    'olympia.devhub.tasks.flag_binary': {'queue': 'devhub'},
    'olympia.devhub.tasks.get_preview_sizes': {'queue': 'devhub'},
    'olympia.devhub.tasks.handle_file_validation_result': {'queue': 'devhub'},
    'olympia.devhub.tasks.handle_upload_validation_result': {
        'queue': 'devhub'},
    'olympia.devhub.tasks.resize_icon': {'queue': 'devhub'},
    'olympia.devhub.tasks.resize_preview': {'queue': 'devhub'},
    'olympia.devhub.tasks.send_welcome_email': {'queue': 'devhub'},
    'olympia.devhub.tasks.submit_file': {'queue': 'devhub'},
    'olympia.devhub.tasks.validate_file': {'queue': 'devhub'},
    'olympia.devhub.tasks.validate_file_path': {'queue': 'devhub'},

    # This is currently used only by validation tasks.
    # This puts the chord_unlock task on the devhub queue. Which means anything
    # that uses chord() or group() must also be running in this queue or must
    # be on a worker that listens to the same queue.
    'celery.chord_unlock': {'queue': 'devhub'},
    'olympia.devhub.tasks.compatibility_check': {'queue': 'devhub'},

    # Images.
    'olympia.bandwagon.tasks.resize_icon': {'queue': 'images'},
    'olympia.users.tasks.resize_photo': {'queue': 'images'},
    'olympia.users.tasks.delete_photo': {'queue': 'images'},
    'olympia.devhub.tasks.resize_icon': {'queue': 'images'},
    'olympia.devhub.tasks.resize_preview': {'queue': 'images'},

    # AMO validator.
    'olympia.zadmin.tasks.bulk_validate_file': {'queue': 'limited'},

    # AMO
    'olympia.amo.tasks.delete_anonymous_collections': {'queue': 'amo'},
    'olympia.amo.tasks.delete_logs': {'queue': 'amo'},
    'olympia.amo.tasks.delete_stale_contributions': {'queue': 'amo'},
    'olympia.amo.tasks.migrate_editor_eventlog': {'queue': 'amo'},
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
    'olympia.bandwagon.tasks.resize_icon': {'queue': 'bandwagon'},

    # Editors
    'olympia.editors.tasks.add_commentlog': {'queue': 'editors'},
    'olympia.editors.tasks.add_versionlog': {'queue': 'editors'},
    'olympia.editors.tasks.approve_rereview': {'queue': 'editors'},
    'olympia.editors.tasks.reject_rereview': {'queue': 'editors'},
    'olympia.editors.tasks.send_mail': {'queue': 'editors'},

    # Files
    'olympia.files.tasks.extract_file': {'queue': 'files'},
    'olympia.files.tasks.fix_let_scope_bustage_in_addons': {'queue': 'files'},

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
    'olympia.reviews.models.check_spam': {'queue': 'reviews'},
    'olympia.reviews.tasks.addon_bayesian_rating': {'queue': 'reviews'},
    'olympia.reviews.tasks.addon_grouped_rating': {'queue': 'reviews'},
    'olympia.reviews.tasks.addon_review_aggregates': {'queue': 'reviews'},
    'olympia.reviews.tasks.update_denorm': {'queue': 'reviews'},


    # Stats
    'olympia.stats.tasks.addon_total_contributions': {'queue': 'stats'},
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
    'olympia.tags.tasks.clean_tag': {'queue': 'tags'},
    'olympia.tags.tasks.update_all_tag_stats': {'queue': 'tags'},
    'olympia.tags.tasks.update_tag_stat': {'queue': 'tags'},

    # Users
    'olympia.users.tasks.delete_photo': {'queue': 'users'},
    'olympia.users.tasks.resize_photo': {'queue': 'users'},
    'olympia.users.tasks.update_user_ratings_task': {'queue': 'users'},

    # Zadmin
    'olympia.zadmin.tasks.add_validation_jobs': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.admin_email': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.celery_error': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.fetch_langpack': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.fetch_langpacks': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.notify_compatibility': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.notify_compatibility_chunk': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.tally_validation_results': {'queue': 'zadmin'},
    'olympia.zadmin.tasks.update_maxversions': {'queue': 'zadmin'},
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
HAS_SYSLOG = True  # syslog is used if HAS_SYSLOG and NOT DEBUG.
SYSLOG_TAG = "http_app_addons"
SYSLOG_TAG2 = "http_app_addons2"
# See PEP 391 and log_settings.py for formatting help.  Each section of
# LOGGING will get merged into the corresponding section of
# log_settings.py. Handlers and log levels are set up automatically based
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
CSP_CONNECT_SRC = (
    "'self'",
    'https://sentry.prod.mozaws.net',
)
CSP_FONT_SRC = (
    "'self'",
    PROD_CDN_HOST,
)
CSP_FRAME_SRC = (
    "'self'",
    'https://ic.paypal.com',
    'https://paypal.com',
    'https://www.google.com/recaptcha/',
    'https://www.paypal.com',
)
CSP_IMG_SRC = (
    "'self'",
    'data:',  # Used in inlined mobile css.
    'blob:',  # Needed for image uploads.
    'https://www.paypal.com',
    ANALYTICS_HOST,
    PROD_CDN_HOST,
    'https://static.addons.mozilla.net',  # CDN origin server.
    'https://sentry.prod.mozaws.net',
)
CSP_MEDIA_SRC = (
    'https://videos.cdn.mozilla.net',
)
CSP_OBJECT_SRC = ("'none'",)

# https://addons.mozilla.org is needed for about:addons because
# the discovery pane's origin is https://services.addons.mozilla.org
# and as a result 'self' doesn't match requests to addons.mozilla.org.
CSP_SCRIPT_SRC = (
    "'self'",
    'https://addons.mozilla.org',
    'https://www.paypalobjects.com',
    'https://www.google.com/recaptcha/',
    'https://www.gstatic.com/recaptcha/',
    ANALYTICS_HOST,
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

# RECAPTCHA: overload the following key setttings in local_settings.py
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

# Full path or executable path (relative to $PATH) of the spidermonkey js
# binary.  It must be a version compatible with amo-validator.
SPIDERMONKEY = None

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

# If the users's Firefox has a version number greater than this we consider it
# a beta.
MIN_BETA_VERSION = '3.7'

DEFAULT_SUGGESTED_CONTRIBUTION = 5

# Path to `ps`.
PS_BIN = '/bin/ps'

BLOCKLIST_COOKIE = 'BLOCKLIST_v1'

# The maximum file size that is shown inside the file viewer.
FILE_VIEWER_SIZE_LIMIT = 1048576
# The maximum file size that you can have inside a zip file.
FILE_UNZIP_SIZE_LIMIT = 104857600

# How long to delay tasks relying on file system to cope with NFS lag.
NFS_LAG_DELAY = 3

# A whitelist of domains that the authentication script will redirect to upon
# successfully logging in or out.
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

# This is the signing server for signing fully reviewed files.
SIGNING_SERVER = ''
# This is the signing server for signing preliminary reviewed files.
PRELIMINARY_SIGNING_SERVER = ''
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

# The configuration for the client that speaks to solitude.
# A tuple of the solitude hosts.
SOLITUDE_HOSTS = ('',)

# The oAuth key and secret that solitude needs.
SOLITUDE_KEY = ''
SOLITUDE_SECRET = ''
# The timeout we'll give solitude.
SOLITUDE_TIMEOUT = 10

# The OAuth keys to connect to the solitude host specified above.
SOLITUDE_OAUTH = {'key': '', 'secret': ''}

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

# Modify the user-agents we check for in django-mobility
# (Android has since changed its user agent).
MOBILE_USER_AGENTS = ('mozilla.+mobile|android|fennec|iemobile|'
                      'iphone|opera (?:mini|mobi)')

# Credentials for accessing Google Analytics stats.
GOOGLE_ANALYTICS_CREDENTIALS = {}

# Which domain to access GA stats for. If not set, defaults to DOMAIN.
GOOGLE_ANALYTICS_DOMAIN = None

# Used for general web API access.
GOOGLE_API_CREDENTIALS = ''

# Google translate settings.
GOOGLE_TRANSLATE_API_URL = 'https://www.googleapis.com/language/translate/v2'
GOOGLE_TRANSLATE_REDIRECT_URL = (
    'https://translate.google.com/#auto/{lang}/{text}')

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
WHITELISTED_CLIENTS_EMAIL_API = []

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
GUARDED_ADDONS_PATH = ROOT + u'/guarded-addons'


# These are key files that must be present on disk to encrypt/decrypt certain
# database fields.
AES_KEYS = {
    # 'api_key:secret': os.path.join(ROOT, 'path', 'to', 'file.key'),
}

# Time in seconds for how long a JWT auth token created by developers with
# their API key can live. When developers are creating auth tokens they cannot
# set the expiration any longer than this.
MAX_APIKEY_JWT_AUTH_TOKEN_LIFETIME = 60

# django-rest-framework-jwt settings:
JWT_AUTH = {
    # Use HMAC using SHA-256 hash algorithm. It should be the default, but we
    # want to make sure it does not change behind our backs.
    # See https://github.com/jpadilla/pyjwt/blob/master/docs/algorithms.rst
    'JWT_ALGORITHM': 'HS256',

    # This adds some padding to timestamp validation in case client/server
    # clocks are off.
    'JWT_LEEWAY': 5,

    # Expiration for non-apikey jwt tokens. Since this will be used by our
    # frontend clients we want a longer expiration than normal, matching the
    # session cookie expiration.
    'JWT_EXPIRATION_DELTA': datetime.timedelta(seconds=SESSION_COOKIE_AGE),

    # We don't allow refreshes, instead we simply have a long duration.
    'JWT_ALLOW_REFRESH': False,

    # Prefix for non-apikey jwt tokens. Should be different from 'JWT' which we
    # already used for api key tokens.
    'JWT_AUTH_HEADER_PREFIX': 'Bearer',
}

REST_FRAMEWORK = {
    # Set this because the default is to also include:
    #   'rest_framework.renderers.BrowsableAPIRenderer'
    # Which it will try to use if the client accepts text/html.
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'olympia.api.authentication.JSONWebTokenAuthentication',
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
}

# This is the DSN to the local Sentry service. It might be overidden in
# site-specific settings files as well.
SENTRY_DSN = os.environ.get('SENTRY_DSN')
