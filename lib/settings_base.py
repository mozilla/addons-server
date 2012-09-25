# -*- coding: utf-8 -*-
# Django settings for zamboni project.

import os
import logging
import socket

from django.utils.functional import lazy
from metlog.config import client_from_dict_config

WAFFLE_TABLE_SUFFIX = 'amo'
LOG_TABLE_SUFFIX = ''
EVENT_TABLE_SUFFIX = ''

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

# Make filepaths relative to the root of zamboni.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = lambda *a: os.path.join(ROOT, *a)

# We need to track this because hudson can't just call its checkout "zamboni".
# It puts it in a dir called "workspace".  Way to be, hudson.
ROOT_PACKAGE = os.path.basename(ROOT)

DEBUG = True
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = True

# need to view JS errors on a remote device? (requires node)
# > npm install now
# > node media/js/debug/remote_debug_server.node.js
# REMOTE_JS_DEBUG = 'localhost:37767'
# then connect to http://localhost:8080/ to view
REMOTE_JS_DEBUG = False

# LESS CSS OPTIONS (Debug only)
LESS_PREPROCESS = False  # Compile LESS with Node, rather than client-side JS?
LESS_LIVE_REFRESH = False  # Refresh the CSS on save?
LESS_BIN = 'lessc'

# Path to uglifyjs. When not None, this will be used to minify JavaScript
# instead of YUI.
UGLIFY_BIN = None

ADMINS = (
    # ('Your Name', 'your_email@domain.com'),
)
MANAGERS = ADMINS

FLIGTAR = 'amo-admins@mozilla.org'
EDITORS_EMAIL = 'amo-editors@mozilla.org'
SENIOR_EDITORS_EMAIL = 'amo-admin-reviews@mozilla.org'
MARKETPLACE_EMAIL = 'amo-marketplace@mozilla.org'
ABUSE_EMAIL = 'marketplace-abuse@mozilla.org'
NOBODY_EMAIL = 'nobody@mozilla.org'

DATABASES = {
    'default': {
        'NAME': 'zamboni',
        'ENGINE': 'django.db.backends.mysql',
        'HOST': '',
        'PORT': '',
        'USER': '',
        'PASSWORD': '',
        'OPTIONS': {'init_command': 'SET storage_engine=InnoDB'},
        'TEST_CHARSET': 'utf8',
        'TEST_COLLATION': 'utf8_general_ci',
    },
}

# A database to be used by the services scripts, which does not use Django.
# The settings can be copied from DATABASES, but since its not a full Django
# database connection, only some values are supported.
SERVICES_DATABASE = {
    'NAME': 'zamboni',
    'USER': '',
    'PASSWORD': '',
    'HOST': '',
}

DATABASE_ROUTERS = ('multidb.PinningMasterSlaveRouter',)

# For use django-mysql-pool backend.
DATABASE_POOL_ARGS = {
    'max_overflow': 10,
    'pool_size': 5,
    'recycle': 300
}

# Put the aliases for your slave databases in this list.
SLAVE_DATABASES = []

# Local time zone for this installation. Choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# although not all choices may be available on all operating systems.
# If running in a Windows environment this must be set to the same as your
# system time zone.
TIME_ZONE = 'America/Los_Angeles'

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-US'

# Accepted locales
# Note: If you update this list, don't forget to also update the locale
# permissions in the database.
AMO_LANGUAGES = (
    'af', 'ar', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'en-US', 'es', 'eu', 'fa',
    'fi', 'fr', 'ga-IE', 'he', 'hu', 'id', 'it', 'ja', 'ko', 'mn', 'nl', 'pl',
    'pt-BR', 'pt-PT', 'ro', 'ru', 'sk', 'sl', 'sq', 'sv-SE', 'uk', 'vi',
    'zh-CN', 'zh-TW',
)

# Explicit conversion of a shorter language code into a more specific one.
SHORTER_LANGUAGES = {
    'en': 'en-US', 'ga': 'ga-IE', 'pt': 'pt-PT', 'sv': 'sv-SE', 'zh': 'zh-CN'
}

# Not shown on the site, but .po files exist and these are available on the
# L10n dashboard.  Generally languages start here and move into AMO_LANGUAGES.
HIDDEN_LANGUAGES = ('cy', 'sr', 'sr-Latn', 'tr')


def lazy_langs(languages):
    from product_details import product_details
    if not product_details.languages:
        return {}
    return dict([(i.lower(), product_details.languages[i]['native'])
                 for i in languages])

# Where product details are stored see django-mozilla-product-details
PROD_DETAILS_DIR = path('lib/product_json')

# Override Django's built-in with our native names
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
RTL_LANGUAGES = ('ar', 'fa', 'fa-IR', 'he')

LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])

# Tower / L10n
LOCALE_PATHS = (path('locale'),)
TEXT_DOMAIN = 'messages'
STANDALONE_DOMAINS = [TEXT_DOMAIN, 'javascript']
TOWER_KEYWORDS = {
    '_lazy': None,
}
TOWER_ADD_HEADERS = True

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

# When True, the addon API should include performance data.
API_SHOW_PERF_DATA = True

# The domain of the mobile site.
MOBILE_DOMAIN = 'm.%s' % DOMAIN

# The full url of the mobile site.
MOBILE_SITE_URL = 'http://%s' % MOBILE_DOMAIN

OAUTH_CALLBACK_VIEW = 'api.views.request_token_ready'

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = path('media')

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = '/media/'

# Absolute path to a temporary storage area
TMP_PATH = path('tmp')

# When True, create a URL root /tmp that serves files in your temp path.
# This is useful for development to view upload pics, etc.
# NOTE: This only works when DEBUG is also True.
SERVE_TMP_PATH = False

# Absolute path to a writable directory shared by all servers. No trailing
# slash.  Example: /data/
NETAPP_STORAGE = TMP_PATH

#  File path for storing XPI/JAR files (or any files associated with an
#  add-on). Example: /mnt/netapp_amo/addons.mozilla.org-remora/files
ADDONS_PATH = NETAPP_STORAGE + '/addons'

# Like ADDONS_PATH but protected by the app. Used for storing files that should
# not be publicly accessible (like disabled add-ons).
GUARDED_ADDONS_PATH = NETAPP_STORAGE + '/guarded-addons'

# Used for storing watermarked addons for the app.
WATERMARKED_ADDONS_PATH = NETAPP_STORAGE + '/watermarked-addons'

# Used for storing signed webapps.
SIGNED_APPS_PATH = NETAPP_STORAGE + '/signed-apps'
# Special reviewer signed ones for special people.
SIGNED_APPS_REVIEWER_PATH = NETAPP_STORAGE + '/signed-apps-reviewer'

# Absolute path to a writable directory shared by all servers. No trailing
# slash.
# Example: /data/uploads
UPLOADS_PATH = NETAPP_STORAGE + '/uploads'

# File path for add-on files that get rsynced to mirrors.
# /mnt/netapp_amo/addons.mozilla.org-remora/public-staging
MIRROR_STAGE_PATH = NETAPP_STORAGE + '/public-staging'

# paths that don't require an app prefix
SUPPORTED_NONAPPS = ('about', 'admin', 'apps', 'blocklist', 'credits',
                     'developer_agreement', 'developer_faq', 'developers',
                     'editors', 'faq', 'google1f3e37b7351799a5.html', 'img',
                     'jsi18n', 'localizers', 'media', 'review_guide',
                     'robots.txt', 'statistics', 'services', 'sunbird')
DEFAULT_APP = 'firefox'

# paths that don't require a locale prefix
SUPPORTED_NONLOCALES = ('google1f3e37b7351799a5.html', 'img', 'media',
                        'robots.txt', 'services', 'downloads', 'blocklist')

# Make this unique, and don't share it with anybody.
SECRET_KEY = 'r#%9w^o_80)7f%!_ir5zx$tu3mupw9u%&s!)-_q%gy7i+fhx#)'

# Templates

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    #'jingo.Loader',
    'django.template.loaders.filesystem.Loader',
    'django.template.loaders.app_directories.Loader',
)

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.contrib.auth.context_processors.auth',
    'django.core.context_processors.debug',
    'django.core.context_processors.media',
    'django.core.context_processors.request',
    'session_csrf.context_processor',

    'django.contrib.messages.context_processors.messages',

    'amo.context_processors.app',
    'amo.context_processors.i18n',
    'amo.context_processors.global_settings',
    'amo.context_processors.static_url',
    'jingo_minify.helpers.build_ids',
)

TEMPLATE_DIRS = (
    path('templates'),
)


def JINJA_CONFIG():
    import jinja2
    from django.conf import settings
    from django.core.cache import cache
    config = {'extensions': ['tower.template.i18n', 'amo.ext.cache',
                             'jinja2.ext.do',
                             'jinja2.ext.with_', 'jinja2.ext.loopcontrols'],
              'finalize': lambda x: x if x is not None else ''}
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
    'amo.middleware.LocaleAndAppURLMiddleware',
    # Mobile detection should happen in Zeus.
    'mobility.middleware.DetectMobileMiddleware',
    'mobility.middleware.XMobileMiddleware',
    # Disabled until ready:
    # 'amo.middleware.LazyPjaxMiddleware',
    'amo.middleware.RemoveSlashMiddleware',

    # Munging REMOTE_ADDR must come before ThreadRequest.
    'commonware.middleware.SetRemoteAddrFromForwardedFor',

    'commonware.middleware.FrameOptionsHeader',
    'commonware.middleware.StrictTransportMiddleware',
    'multidb.middleware.PinningRouterMiddleware',
    'waffle.middleware.WaffleMiddleware',

    'csp.middleware.CSPMiddleware',

    'amo.middleware.CommonMiddleware',
    'amo.middleware.NoVarySessionMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'commonware.log.ThreadRequestMiddleware',
    'apps.search.middleware.ElasticsearchExceptionMiddleware',
    'session_csrf.CsrfMiddleware',

    # This should come after authentication middleware
    'access.middleware.ACLMiddleware',

    'commonware.middleware.ScrubRequestOnException',
)

# Auth
AUTHENTICATION_BACKENDS = (
    'django_browserid.auth.BrowserIDBackend',
    'users.backends.AmoUserBackend',
    'cake.backends.SessionBackend',
)
AUTH_PROFILE_MODULE = 'users.UserProfile'

# Override this in the site settings.
ROOT_URLCONF = 'lib.urls_base'

INSTALLED_APPS = (
    'amo',  # amo comes first so it always takes precedence.
    'abuse',
    'access',
    'addons',
    'api',
    'applications',
    'bandwagon',
    'blocklist',
    'browse',
    'compat',
    'cronjobs',
    'csp',
    'devhub',
    'discovery',
    'editors',
    'extras',
    'files',
    'jingo_minify',
    'market',
    'localizers',
    'pages',
    'perf',
    'product_details',
    'reviews',
    'search',
    'sharing',
    'stats',
    'tags',
    'tower',  # for ./manage.py extract
    'translations',
    'users',
    'versions',
    'mkt.webapps',
    'zadmin',
    'cake',

    # Third party apps
    'djcelery',
    'django_extensions',
    'django_nose',
    'gunicorn',
    'raven.contrib.django',
    'piston',
    'waffle',

    # Django contrib apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.messages',
    'django.contrib.sessions',

    # Has to load after auth
    'django_browserid',
    'django_statsd',
    'radagast',
)

# These apps will be removed from INSTALLED_APPS in a production environment.
DEV_APPS = (
    'django_nose',
)

# Tests
TEST_RUNNER = 'test_utils.runner.RadicalTestSuiteRunner'
NOSE_ARGS = [
    '--with-fixture-bundling',
    '--exclude=mkt/*',
]

# If you want to run Selenium tests, you'll need to have a server running.
# Then give this a dictionary of settings.  Something like:
#    'HOST': 'localhost',
#    'PORT': 4444,
#    'BROWSER': '*firefox', # Alternative: *safari
SELENIUM_CONFIG = {}

# Tells the extract script what files to look for l10n in and what function
# handles the extraction.  The Tower library expects this.
DOMAIN_METHODS = {
    'messages': [
        ('apps/**.py',
            'tower.management.commands.extract.extract_tower_python'),
        ('apps/**/templates/**.html',
            'tower.management.commands.extract.extract_tower_template'),
        ('templates/**.html',
            'tower.management.commands.extract.extract_tower_template'),
        ('mkt/**.py',
            'tower.management.commands.extract.extract_tower_python'),
        ('mkt/**/templates/**.html',
            'tower.management.commands.extract.extract_tower_template'),
        ('mkt/templates/**.html',
            'tower.management.commands.extract.extract_tower_template'),
    ],
    'lhtml': [
        ('**/templates/**.lhtml',
            'tower.management.commands.extract.extract_tower_template'),
    ],
    'javascript': [
        # We can't say **.js because that would dive into mochikit and timeplot
        # and all the other baggage we're carrying.  Timeplot, in particular,
        # crashes the extractor with bad unicode data.
        ('media/js/*.js', 'javascript'),
        ('media/js/amo2009/**.js', 'javascript'),
        ('media/js/impala/**.js', 'javascript'),
        ('media/js/zamboni/**.js', 'javascript'),
        ('media/js/mkt/**.js', 'javascript'),
    ],
}

# Bundles is a dictionary of two dictionaries, css and js, which list css files
# and js files that can be bundled together by the minify app.
MINIFY_BUNDLES = {
    'css': {
        # CSS files common to the entire site.
        'zamboni/css': (
            'css/legacy/main.css',
            'css/legacy/main-mozilla.css',
            'css/legacy/jquery-lightbox.css',
            'css/legacy/autocomplete.css',
            'css/zamboni/zamboni.css',
            'css/global/headerfooter.css',
            'css/zamboni/tags.css',
            'css/zamboni/tabs.css',
            'css/impala/formset.less',
            'css/impala/suggestions.less',
            'css/impala/header.less',
            'css/impala/moz-tab.css',
            'css/impala/footer.less',
            'css/impala/faux-zamboni.less',
            'css/impala/collection-stats.less',
        ),
        'zamboni/impala': (
            'css/impala/base.css',
            'css/legacy/jquery-lightbox.css',
            'css/impala/site.less',
            'css/impala/typography.less',
            'css/global/headerfooter.css',
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
            'css/impala/sharing.less',
            'css/impala/abuse.less',
            'css/impala/paginator.less',
            'css/impala/listing.less',
            'css/impala/versions.less',
            'css/impala/users.less',
            'css/impala/collections.less',
            'css/impala/tooltips.less',
            'css/impala/search.less',
            'css/impala/suggestions.less',
            'css/impala/colorpicker.less',
            'css/impala/personas.less',
            'css/impala/login.less',
            'css/impala/dictionaries.less',
            'css/impala/apps.less',
            'css/impala/formset.less',
            'css/impala/tables.less',
            'css/impala/compat.less',
            'css/impala/localizers.less',
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
            'css/devhub/packager.less',
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
        ),
        'zamboni/editors': (
            'css/zamboni/editors.css',
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
        ),
        'zamboni/admin': (
            'css/zamboni/admin-django.css',
            'css/zamboni/admin-mozilla.css',
            'css/zamboni/admin_features.css'
        ),
    },
    'js': {
        # JS files common to the entire site (pre-impala).
        'common': (
            'js/lib/jquery-1.6.4.js',
            'js/lib/underscore.js',
            'js/zamboni/browser.js',
            'js/amo2009/addons.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/lib/format.js',
            'js/lib/jquery.cookie.js',
            'js/zamboni/storage.js',
            'js/zamboni/apps.js',
            'js/zamboni/buttons.js',
            'js/zamboni/tabs.js',
            'js/common/keys.js',

            # jQuery UI
            'js/lib/jquery-ui/jquery.ui.core.js',
            'js/lib/jquery-ui/jquery.ui.position.js',
            'js/lib/jquery-ui/jquery.ui.widget.js',
            'js/lib/jquery-ui/jquery.ui.mouse.js',
            'js/lib/jquery-ui/jquery.ui.autocomplete.js',
            'js/lib/jquery-ui/jquery.ui.datepicker.js',
            'js/lib/jquery-ui/jquery.ui.sortable.js',

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
            'js/get-satisfaction-v2.js',
            'js/zamboni/contributions.js',
            'js/zamboni/addon_details.js',
            'js/impala/abuse.js',
            'js/zamboni/reviews.js',

            # Personas
            'js/lib/jquery.hoverIntent.js',
            'js/zamboni/personas_core.js',
            'js/zamboni/personas.js',

            # Collections
            'js/zamboni/collections.js',

            # Performance
            'js/zamboni/perf.js',

            # Users
            'js/zamboni/users.js',

            # Fix-up outgoing links
            'js/zamboni/outgoing_links.js',

            # Hover delay for global header
            'js/global/menu.js',

            # Password length and strength
            'js/zamboni/password-strength.js',

            # Search suggestions
            'js/impala/forms.js',
            'js/impala/ajaxcache.js',
            'js/impala/suggestions.js',
            'js/impala/site_suggestions.js',
        ),

        # Impala: Things to be loaded at the top of the page
        'preload': (
            'js/lib/jquery-1.6.4.js',
            'js/impala/preloaded.js'
        ),
        # Impala: Things to be loaded at the bottom
        'impala': (
            'js/lib/underscore.js',
            'js/impala/carousel.js',
            'js/zamboni/browser.js',
            'js/amo2009/addons.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/lib/format.js',
            'js/lib/jquery.cookie.js',
            'js/zamboni/storage.js',
            'js/zamboni/apps.js',
            'js/zamboni/buttons.js',
            'js/lib/jquery.pjax.js',
            'js/impala/footer.js',
            'js/common/keys.js',

            # BrowserID
            'js/zamboni/browserid_support.js',

            # jQuery UI
            'js/lib/jquery-ui/jquery.ui.core.js',
            'js/lib/jquery-ui/jquery.ui.position.js',
            'js/lib/jquery-ui/jquery.ui.widget.js',
            'js/lib/jquery-ui/jquery.ui.mouse.js',
            'js/lib/jquery-ui/jquery.ui.autocomplete.js',
            'js/lib/jquery-ui/jquery.ui.datepicker.js',
            'js/lib/jquery-ui/jquery.ui.sortable.js',

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
            'js/get-satisfaction-v2.js',
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

            # Collections
            'js/zamboni/collections.js',
            'js/impala/collections.js',

            # Performance
            'js/zamboni/perf.js',

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

            # Fix-up outgoing links
            'js/zamboni/outgoing_links.js',
            'js/lib/stick.js',
        ),
        'zamboni/discovery': (
            'js/lib/jquery-1.6.4.js',
            'js/lib/underscore.js',
            'js/zamboni/browser.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/lib/format.js',
            'js/impala/carousel.js',

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
            'js/zamboni/truncation.js',

            'js/impala/promos.js',
            'js/zamboni/discovery_addons.js',
            'js/zamboni/discovery_pane.js',
        ),
        'zamboni/discovery-video': (
            'js/lib/popcorn-1.0.js',
            'js/webtrends/webtrends-v0.1.js',
            'js/zamboni/discovery_video.js',
            'js/zamboni/discovery_tracking.js',
        ),
        'zamboni/devhub': (
            'js/zamboni/truncation.js',
            'js/common/upload-base.js',
            'js/common/upload-addon.js',
            'js/common/upload-image.js',
            'js/impala/formset.js',
            'js/zamboni/devhub.js',
            'js/zamboni/validator.js',
            'js/zamboni/packager.js',
        ),
        'zamboni/editors': (
            'js/zamboni/editors.js',
            'js/lib/highcharts.src.js',
            'js/impala/formset.js',
            'js/lib/jquery.hoverIntent.js',
            'js/lib/jquery.zoomBox.js',
            'js/mkt/themes_review.js',
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
            'js/zamboni/files.js',
        ),
        'zamboni/localizers': (
            'js/zamboni/localizers.js',
        ),
        'zamboni/mobile': (
            'js/lib/jquery-1.6.4.js',
            'js/lib/underscore.js',
            'js/lib/jqmobile.js',
            'js/lib/jquery.cookie.js',
            'js/lib/jquery.pjax.js',
            'js/impala/pjax.js',
            'js/zamboni/apps.js',
            'js/zamboni/browser.js',
            'js/zamboni/init.js',
            'js/impala/capabilities.js',
            'js/lib/format.js',
            'js/zamboni/mobile/buttons.js',
            'js/zamboni/truncation.js',
            'js/impala/footer.js',
            'js/zamboni/personas_core.js',
            'js/zamboni/mobile/personas.js',
            'js/zamboni/helpers.js',
            'js/zamboni/mobile/general.js',
            'js/common/ratingwidget.js',
            'js/zamboni/browserid_support.js',
        ),
        'zamboni/stats': (
            'js/lib/jquery-datepicker.js',
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
MIRROR_DELAY = 30  # Minutes before we serve downloads from mirrors.
MIRROR_URL = 'http://releases.mozilla.org/pub/mozilla.org/addons'
LOCAL_MIRROR_URL = 'https://static.addons.mozilla.net/_files'
PRIVATE_MIRROR_URL = '/_privatefiles'

# File paths
ADDON_ICONS_PATH = UPLOADS_PATH + '/addon_icons'
COLLECTIONS_ICON_PATH = UPLOADS_PATH + '/collection_icons'
PREVIEWS_PATH = UPLOADS_PATH + '/previews'
IMAGEASSETS_PATH = UPLOADS_PATH + '/imageassets'
PERSONAS_PATH = UPLOADS_PATH + '/personas'
USERPICS_PATH = UPLOADS_PATH + '/userpics'
PACKAGER_PATH = os.path.join(TMP_PATH, 'packager')
ADDON_ICONS_DEFAULT_PATH = os.path.join(MEDIA_ROOT, 'img/addon-icons')

PREVIEW_THUMBNAIL_PATH = (PREVIEWS_PATH + '/thumbs/%s/%d.png')
PREVIEW_FULL_PATH = (PREVIEWS_PATH + '/full/%s/%d.%s')
IMAGEASSET_FULL_PATH = (IMAGEASSETS_PATH + '/%s/%d.%s')

# URL paths
# paths for images, e.g. mozcdn.com/amo or '/static'
STATIC_URL = SITE_URL
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + '/img/addon-icons'
ADDON_ICON_BASE_URL = MEDIA_URL + 'img/icons/'
ADDON_ICON_URL = (STATIC_URL +
        '/img/uploads/addon_icons/%s/%s-%s.png?modified=%s')
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        '/img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (STATIC_URL +
        '/img/uploads/previews/full/%s/%d.%s?modified=%d')
IMAGEASSET_FULL_URL = (STATIC_URL +
        '/img/uploads/imageassets/%s/%d.%s?modified=%d')
USERPICS_URL = STATIC_URL + '/img/uploads/userpics/%s/%s/%s.png?modified=%d'
# paths for uploaded extensions
COLLECTION_ICON_URL = (STATIC_URL +
        '/img/uploads/collection_icons/%s/%s.png?m=%s')
NEW_PERSONAS_IMAGE_URL = (STATIC_URL +
                          '/img/uploads/personas/%(id)d/%(file)s')
PERSONAS_IMAGE_URL = ('http://www.getpersonas.com/static/'
                      '%(tens)d/%(units)d/%(id)d/%(file)s')
PERSONAS_IMAGE_URL_SSL = ('https://www.getpersonas.com/static/'
                          '%(tens)d/%(units)d/%(id)d/%(file)s')
PERSONAS_USER_ROOT = 'http://www.getpersonas.com/gallery/designer/%s'
PERSONAS_UPDATE_URL = 'https://www.getpersonas.com/update_check/%d'

# Outgoing URL bouncer
REDIRECT_URL = 'http://outgoing.mozilla.org/v1/'
REDIRECT_SECRET_KEY = ''

PFS_URL = 'https://pfs.mozilla.org/plugins/PluginFinderService.php'
# Allow URLs from these servers. Use full domain names.
REDIRECT_URL_WHITELIST = ['addons.mozilla.org']

# Default to short expiration; check "remember me" to override
SESSION_ENGINE = 'django.contrib.sessions.backends.cached_db'
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 1209600
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_DOMAIN = ".%s" % DOMAIN  # bug 608797
MESSAGE_STORAGE = 'django.contrib.messages.storage.cookie.CookieStorage'

# These should have app+locale at the start to avoid redirects
LOGIN_URL = "/users/login"
LOGOUT_URL = "/users/logout"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
# When logging in with browser ID, a username is created automatically.
# In the case of duplicates, the process is recursive up to this number
# of times.
MAX_GEN_USERNAME_TRIES = 50

# Legacy Settings
# used by old-style CSRF token
CAKE_SESSION_TIMEOUT = 8640

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

# PayPal split for Adaptive Payments.
# A tuple of lists of % and destination.
PAYPAL_CHAINS = ()

# If the refund request is under this amount of seconds, it will be instant.
PAYPAL_REFUND_INSTANT = 30 * 60

# The PayPal cert that we'll use for checking.
# When None, the Mozilla CA bundle is used to look it up.
PAYPAL_CERT = None

# Limit PayPal pre-approvals to certain limits.
PAYPAL_LIMIT_PREAPPROVAL = True

# Contribution limit, one time and monthly
MAX_CONTRIBUTION = 1000

# Email settings
DEFAULT_FROM_EMAIL = "Mozilla Add-ons <nobody@mozilla.org>"

# Email goes to the console by default.  s/console/smtp/ for regular delivery
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Please use all lowercase for the blacklist.
EMAIL_BLACKLIST = (
    'nobody@mozilla.org',
)

# URL for Add-on Validation FAQ.
VALIDATION_FAQ_URL = ('https://wiki.mozilla.org/AMO:Editors/EditorGuide/'
                      'AddonReviews#Step_2:_Automatic_validation')


## Celery
BROKER_HOST = 'localhost'
BROKER_PORT = 5672
BROKER_USER = 'zamboni'
BROKER_PASSWORD = 'zamboni'
BROKER_VHOST = 'zamboni'
BROKER_CONNECTION_TIMEOUT = 0.1
CELERY_RESULT_BACKEND = 'amqp'
CELERY_IGNORE_RESULT = True
CELERY_SEND_TASK_ERROR_EMAILS = True
CELERYD_LOG_LEVEL = logging.INFO
CELERYD_HIJACK_ROOT_LOGGER = False
CELERY_IMPORTS = ('lib.video.tasks', 'lib.metrics')
# We have separate celeryds for processing devhub & images as fast as possible
# Some notes:
# - always add routes here instead of @task(queue=<name>)
# - when adding a queue, be sure to update deploy.py so that it gets restarted
CELERY_ROUTES = {
    # Devhub.
    'devhub.tasks.validator': {'queue': 'devhub'},
    'devhub.tasks.compatibility_check': {'queue': 'devhub'},
    'devhub.tasks.fetch_manifest': {'queue': 'devhub'},
    'devhub.tasks.fetch_icon': {'queue': 'devhub'},
    'devhub.tasks.file_validator': {'queue': 'devhub'},
    'devhub.tasks.packager': {'queue': 'devhub'},

    # Videos.
    'lib.video.tasks.resize_video': {'queue': 'devhub'},

    # Images.
    'bandwagon.tasks.resize_icon': {'queue': 'images'},
    'users.tasks.resize_photo': {'queue': 'images'},
    'users.tasks.delete_photo': {'queue': 'images'},
    'devhub.tasks.resize_icon': {'queue': 'images'},
    'devhub.tasks.resize_preview': {'queue': 'images'},

    # Bulk.
    'zadmin.tasks.bulk_validate_file': {'queue': 'bulk'},
    'zadmin.tasks.tally_validation_results': {'queue': 'bulk'},
    'zadmin.tasks.add_validation_jobs': {'queue': 'bulk'},
    'zadmin.tasks.notify_success': {'queue': 'bulk'},
    'zadmin.tasks.notify_failed': {'queue': 'bulk'},
    'devhub.tasks.flag_binary': {'queue': 'bulk'},
    'stats.tasks.index_update_counts': {'queue': 'bulk'},
    'stats.tasks.index_download_counts': {'queue': 'bulk'},
}

# This is just a place to store these values, you apply them in your
# task decorator, for example:
#   @task(time_limit=CELERY_TIME_LIMITS['lib...']['hard'])
# Otherwise your task will use the default settings.
CELERY_TIME_LIMITS = {
    'lib.video.tasks.resize_video': {'soft': 360, 'hard': 600},
}

# When testing, we always want tasks to raise exceptions. Good for sanity.
CELERY_EAGER_PROPAGATES_EXCEPTIONS = True

# Time in seconds before celery.exceptions.SoftTimeLimitExceeded is raised.
# The task can catch that and recover but should exit ASAP. Note that there is
# a separate, shorter timeout for validation tasks.
CELERYD_TASK_SOFT_TIME_LIMIT = 60 * 2

## Fixture Magic
CUSTOM_DUMPS = {
    'addon': {  # ./manage.py custom_dump addon id
        'primary': 'addons.addon',  # This is our reference model.
        'dependents': [  # These are items we wish to dump.
            # Magic turns this into current_version.files.all()[0].
            'current_version.files.all.0',
            'current_version.apps.all.0',
            'addonuser_set.all.0',
        ],
        'order': ('applications.application', 'translations.translation',
                  'addons.addontype', 'files.platform', 'addons.addon',
                  'versions.license', 'versions.version', 'files.file'),
        'excludes': {
            'addons.addon': ('_current_version',),
        }
    }
}

## Hera (http://github.com/clouserw/hera)
HERA = [{'USERNAME': '',
        'PASSWORD': '',
        'LOCATION': '',
       }]

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
        'amqplib': {'handlers': ['null']},
        'caching.invalidation': {'handlers': ['null']},
        'caching': {'level': logging.WARNING},
        'pyes': {'handlers': ['null']},
        'rdflib': {'handlers': ['null']},
        'suds': {'handlers': ['null']},
        'z.task': {'level': logging.INFO},
        'z.es': {'level': logging.INFO},
        'z.metlog': {'level': logging.INFO},
        's.client': {'level': logging.INFO},
        'nose': {'level': logging.WARNING},
    },
}


METLOG_CONF = {
    'logger': 'zamboni',
    'plugins': {
        'cef': ('metlog_cef.cef_plugin:config_plugin', {}),

        # The sentry_project_id maps to the project ID that
        # the sentry server has assigned to the 'sink' 
        # that raven will send messages into.
        # For dev instances, you can leave the dummy value of
        # 2, but for actual live instances you will want to 
        # make sure your project ID corresponds to what is in 
        # your actual sentry instance.
        'raven': ('metlog_raven.raven_plugin:config_plugin',
                   {'sentry_project_id': 2}),
        },
    'sender': {
        'class': 'metlog.senders.logging.StdLibLoggingSender',
        'logger_name': 'z.metlog',
    },
}

METLOG = client_from_dict_config(METLOG_CONF)

USE_METLOG_FOR_CEF = False
USE_METLOG_FOR_RAVEN = False

CEF_PRODUCT = "amo"

# CSP Settings
CSP_REPORT_URI = '/services/csp/report'
CSP_POLICY_URI = '/services/csp/policy?build=%s' % build_id
CSP_REPORT_ONLY = True

CSP_ALLOW = ("'self'",)
CSP_IMG_SRC = ("'self'", STATIC_URL,
               "https://www.google.com",  # Recaptcha comes from google
               "https://statse.webtrendslive.com",
               "https://www.getpersonas.com",
               "https://s3.amazonaws.com",  # getsatisfaction
              )
CSP_SCRIPT_SRC = ("'self'", STATIC_URL,
                  "https://www.google.com",  # Recaptcha
                  "https://browserid.org",
                  "https://login.persona.org",
                  "https://www.paypalobjects.com",
                  "http://raw.github.com",
                  "https://raw.github.com",
                  )
CSP_STYLE_SRC = ("'self'", STATIC_URL,
                 "http://raw.github.com",
                 "https://raw.github.com",
                )
CSP_OBJECT_SRC = ("'none'",)
CSP_MEDIA_SRC = ("'none'",)
CSP_FRAME_SRC = ("https://s3.amazonaws.com",  # getsatisfaction
                 "https://getsatisfaction.com",  # getsatisfaction
                )
CSP_FONT_SRC = ("'self'", "fonts.mozilla.org", "www.mozilla.org", )
# self is needed for paypal which sends x-frame-options:allow when needed.
# x-frame-options:DENY is sent the rest of the time.
CSP_FRAME_ANCESTORS = ("'self'",)


# Should robots.txt deny everything or disallow a calculated list of URLs we
# don't want to be crawled?  Default is false, disallow everything.
# Also see http://www.google.com/support/webmasters/bin/answer.py?answer=93710
ENGAGE_ROBOTS = False

# Read-only mode setup.
READ_ONLY = False


# Turn on read-only mode in settings_local.py by putting this line
# at the VERY BOTTOM: read_only_mode(globals())
def read_only_mode(env):
    env['READ_ONLY'] = True

    # Replace the default (master) db with a slave connection.
    if not env.get('SLAVE_DATABASES'):
        raise Exception("We need at least one slave database.")
    slave = env['SLAVE_DATABASES'][0]
    env['DATABASES']['default'] = env['DATABASES'][slave]

    # No sessions without the database, so disable auth.
    env['AUTHENTICATION_BACKENDS'] = ('users.backends.NoAuthForYou',)

    # Add in the read-only middleware before csrf middleware.
    extra = 'amo.middleware.ReadOnlyMiddleware'
    before = 'session_csrf.CsrfMiddleware'
    m = list(env['MIDDLEWARE_CLASSES'])
    m.insert(m.index(before), extra)
    env['MIDDLEWARE_CLASSES'] = tuple(m)


# Uploaded file limits
MAX_ICON_UPLOAD_SIZE = 4 * 1024 * 1024
MAX_IMAGE_UPLOAD_SIZE = 4 * 1024 * 1024  # Image assets (tiles, promos)
MAX_VIDEO_UPLOAD_SIZE = 4 * 1024 * 1024
MAX_PHOTO_UPLOAD_SIZE = MAX_ICON_UPLOAD_SIZE
MAX_PERSONA_UPLOAD_SIZE = 300 * 1024
MAX_WEBAPP_UPLOAD_SIZE = 2 * 1024 * 1024

# RECAPTCHA - copy all three statements to settings_local.py
RECAPTCHA_PUBLIC_KEY = ''
RECAPTCHA_PRIVATE_KEY = ''
RECAPTCHA_URL = ('https://www.google.com/recaptcha/api/challenge?k=%s' %
                 RECAPTCHA_PUBLIC_KEY)
RECAPTCHA_AJAX_URL = (
    'https://www.google.com/recaptcha/api/js/recaptcha_ajax.js')

# Send Django signals asynchronously on a background thread.
ASYNC_SIGNALS = True

# Performance notes on add-ons
PERFORMANCE_NOTES = False

# Used to flag slow addons.
# If slowness of addon is THRESHOLD percent slower, show a warning.
PERF_THRESHOLD = 25

REDIS_BACKENDS = {'master': 'redis://localhost:6379?socket_timeout=0.5'}

# Directory of JavaScript test files for django_qunit to run
QUNIT_TEST_DIRECTORY = os.path.join(MEDIA_ROOT, 'js', 'zamboni', 'tests')

# Full path or executable path (relative to $PATH) of the spidermonkey js
# binary.  It must be a version compatible with amo-validator
SPIDERMONKEY = None
VALIDATE_ADDONS = True
# Number of seconds before celery tasks will abort addon validation:
VALIDATOR_TIMEOUT = 110

# When True include full tracebacks in JSON. This is useful for QA on preview.
EXPOSE_VALIDATOR_TRACEBACKS = False

# Max number of warnings/errors to show from validator. Set to None for no
# limit.
VALIDATOR_MESSAGE_LIMIT = 500

# Feature flags
SEARCH_EXCLUDE_PERSONAS = True
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

# How long to delay modify updates to cope with alleged NFS slowness.
MODIFIED_DELAY = 3

# This is a list of dictionaries that we should generate compat info for.
# app: should match amo.FIREFOX.id.
# main: the app version we're generating compat info for.
# versions: version numbers to show in comparisons.
# previous: the major version before :main.
COMPAT = (
    # Firefox.
    dict(app=1, main='15.0', versions=('15.0', '15.0a2', '15.0a1'),
         previous='14.0'),
    dict(app=1, main='14.0', versions=('14.0', '14.0a2', '14.0a1'),
         previous='13.0'),
    dict(app=1, main='13.0', versions=('13.0', '13.0a2', '13.0a1'),
         previous='12.0'),
    dict(app=1, main='12.0', versions=('12.0', '12.0a2', '12.0a1'),
         previous='11.0'),
    dict(app=1, main='11.0', versions=('11.0', '11.0a2', '11.0a1'),
         previous='10.0'),
    dict(app=1, main='10.0', versions=('10.0', '10.0a2', '10.0a1'),
         previous='9.0'),
    dict(app=1, main='9.0', versions=('9.0', '9.0a2', '9.0a1'),
         previous='8.0'),
    dict(app=1, main='8.0', versions=('8.0', '8.0a2', '8.0a1'),
         previous='7.0'),
    dict(app=1, main='7.0', versions=('7.0', '7.0a2', '7.0a1'),
         previous='6.0'),
    dict(app=1, main='6.0', versions=('6.0', '6.0a2', '6.0a1'),
         previous='5.0'),
    dict(app=1, main='5.0', versions=('5.0', '5.0a2', '5.0a1'),
         previous='4.0'),
    dict(app=1, main='4.0', versions=('4.0', '4.0a1', '3.7a'),
         previous='3.6'),
    # Thunderbird.
    dict(app=18, main='15.0', versions=('15.0', '15.0a2', '15.0a1'),
         previous='14.0'),
    dict(app=18, main='14.0', versions=('14.0', '14.0a2', '14.0a1'),
         previous='13.0'),
    dict(app=18, main='13.0', versions=('13.0', '13.0a2', '13.0a1'),
         previous='12.0'),
    dict(app=18, main='12.0', versions=('12.0', '12.0a2', '12.0a1'),
         previous='11.0'),
    dict(app=18, main='11.0', versions=('11.0', '11.0a2', '11.0a1'),
         previous='10.0'),
    dict(app=18, main='10.0', versions=('10.0', '10.0a2', '10.0a1'),
         previous='9.0'),
    dict(app=18, main='9.0', versions=('9.0', '9.0a2', '9.0a1'),
         previous='8.0'),
    dict(app=18, main='8.0', versions=('8.0', '8.0a2', '8.0a1'),
         previous='7.0'),
    dict(app=18, main='7.0', versions=('7.0', '7.0a2', '7.0a1'),
         previous='6.0'),
    dict(app=18, main='6.0', versions=('6.0', '6.0a2', '6.0a1'),
         previous='5.0'),
    # Seamonkey.
    dict(app=59, main='2.3', versions=('2.3', '2.3b', '2.3a'),
         previous='2.2'),
)

# Latest nightly version of Firefox.
NIGHTLY_VERSION = COMPAT[0]['main']

# Default minimum version of Firefox/Thunderbird for Add-on Packager.
DEFAULT_MINVER = COMPAT[4]['main']

# URL for reporting arecibo errors too. If not set, won't be sent.
ARECIBO_SERVER_URL = ""

# A whitelist of domains that the authentication script will redirect to upon
# successfully logging in or out.
VALID_LOGIN_REDIRECTS = {
    'builder': 'https://builder.addons.mozilla.org',
    'builderstage': 'https://builder-addons.allizom.org',
    'buildertrunk': 'https://builder-addons-dev.allizom.org',
}

# Secret key we send to builder so we can trust responses from the builder.
BUILDER_SECRET_KEY = 'love will tear us apart'
# The builder URL we hit to upgrade jetpacks.
BUILDER_UPGRADE_URL = 'https://addons.mozilla.org/services/builder'
BUILDER_VERSIONS_URL = ('https://builder.addons.mozilla.org/repackage/' +
                        'sdk-versions/')

## elasticsearch
ES_HOSTS = ['127.0.0.1:9200']
ES_INDEXES = {'default': 'amo',
              'update_counts': 'amo_stats',
              'download_counts': 'amo_stats',
              'stats_contributions': 'amo_stats',
              'stats_collections_counts': 'amo_stats',
              'users_install': 'amo_stats'}
ES_TIMEOUT = 30

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

# URL to the service that triggers addon performance tests.  See devhub.perf.
PERF_TEST_URL = 'http://areweperftestingyet.com/trigger.cgi'
PERF_TEST_TIMEOUT = 5  # seconds

# IP addresses of servers we use as proxies.
KNOWN_PROXIES = []

# Blog URL
DEVELOPER_BLOG_URL = 'http://blog.mozilla.com/addons/feed/'

LOGIN_RATELIMIT_USER = 5
LOGIN_RATELIMIT_ALL_USERS = '15/m'

# The verification URL, the addon id will be appended to this. This will
# have to be altered to the right domain for each server, eg:
# https://receiptcheck.addons.mozilla.org/verify/
WEBAPPS_RECEIPT_URL = '%s/verify/' % SITE_URL
# The key we'll use to sign webapp receipts.
WEBAPPS_RECEIPT_KEY = ''
# The expiry that we will add into the receipt.
# Set to 6 months for the next little while.
WEBAPPS_RECEIPT_EXPIRY_SECONDS = 60 * 60 * 24 * 182
# Send a new receipt back when it expires.
WEBAPPS_RECEIPT_EXPIRED_SEND = False

# How long a watermarked addon should be re-used for, after this
# time it will be regenerated.
WATERMARK_REUSE_SECONDS = 1800
# How long a watermarked addon should wait before being deleted
# by a cron. Setting this far apart from the reuse flag so that we
# shouldn't have an overlap.
WATERMARK_CLEANUP_SECONDS = 3600
# Used in providing a hash for the download of the addon.
WATERMARK_SECRET_KEY = ''

CSRF_FAILURE_VIEW = 'amo.views.csrf_failure'

# CSS selector for what part of the response to return in an X-PJAX request
PJAX_SELECTOR = '#page'

# Testing responsiveness without rate limits.
CELERY_DISABLE_RATE_LIMITS = True

# Temporary variables for the app-preview server, set this to True
# if you want to experience app-preview.mozilla.org.
APP_PREVIEW = False

# Super temporary.
MARKETPLACE = False

# Name of view to use for homepage. AMO uses this. Marketplace has its own.
HOME = 'addons.views.home'

# Sets an upper limit on the number of users. If 0, it's ignored. If the
# number of users meets or exceeds this, they can't register.
REGISTER_USER_LIMIT = 0
# Set this token to a string value to enable users to override the
# registration limit. For example, with a token of 'mozillians' anyone can
# bypass the limit by adding ?ro=mozillians to the URL.
REGISTER_OVERRIDE_TOKEN = None

# Default file storage mechanism that holds media.
DEFAULT_FILE_STORAGE = 'amo.utils.LocalFileStorage'

# Defined in the site, this is to allow settings patch to work for tests.
NO_LOGIN_REQUIRED_MODULES = ()
NO_ADDONS_MODULES = ()
NO_CONSUMER_MODULES = ()

# Where to find ffmpeg and totem if it's not in the PATH.
FFMPEG_BINARY = 'ffmpeg'
TOTEM_BINARIES = {'thumbnailer': 'totem-video-thumbnailer',
                  'indexer': 'totem-video-indexer'}
VIDEO_LIBRARIES = ['lib.video.totem', 'lib.video.ffmpeg']

# This is the metrics REST server for receiving data, should be a URL
# including the protocol.
METRICS_SERVER = ''
# And how long we'll give the server to respond.
METRICS_SERVER_TIMEOUT = 10

# Turn on/off the use of the signing server and all the related things. This
# is a temporary flag that we will remove.
SIGNING_SERVER_ACTIVE = False
# This is the signing REST server for signing receipts.
SIGNING_SERVER = ''
# And how long we'll give the server to respond.
SIGNING_SERVER_TIMEOUT = 10

# True when the Django app is running from the test suite.
IN_TEST_SUITE = False

# Until bug 753421 gets fixed, we're skipping ES tests. Sad times. I know.
# Flip this on in your local settings to experience the joy of ES tests.
RUN_ES_TESTS = False

# The configuration for seclusion the client that speaks to solitude.
# A tuple of the solitude hosts that seclusion will speak to.
SECLUSION_HOSTS = ('',)

# The oAuth key and secret that solitude needs.
SECLUSION_KEY = ''
SECLUSION_SECRET = ''
# The timeout we'll give seclusion. Since this often involves calling Paypal or
# other servers, we are including that in this.
SECLUSION_TIMEOUT = 10

# Temporary flag to work with navigator.mozPay() on devices that don't
# support it natively.
SIMULATE_NAV_PAY = False

# Set this to True if you want region stores (eg: marketplace).
REGION_STORES = False
