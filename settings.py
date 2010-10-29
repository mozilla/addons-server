# -*- coding: utf-8 -*-
# Django settings for zamboni project.

import os
import logging
import socket

import product_details

try:
    # If we have build ids available, we'll grab them here and add them to our
    # CACHE_PREFIX.  This will let us not have to flush memcache during updates
    # and it will let us preload data into it before a production push.
    from build import BUILD_ID_CSS, BUILD_ID_JS
    build_id = "%s%s" % (BUILD_ID_CSS[:2], BUILD_ID_JS[:2])
except ImportError:
    build_id = ""

# Make filepaths relative to settings.
ROOT = os.path.dirname(os.path.abspath(__file__))
path = lambda *a: os.path.join(ROOT, *a)

# We need to track this because hudson can't just call its checkout "zamboni".
# It puts it in a dir called "workspace".  Way to be, hudson.
ROOT_PACKAGE = os.path.basename(ROOT)

DEBUG = True
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = True

ADMINS = (
    # ('Your Name', 'your_email@domain.com'),
)
MANAGERS = ADMINS

FLIGTAR = 'amo-admins@mozilla.org'

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

DATABASE_ROUTERS = ('multidb.PinningMasterSlaveRouter',)

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
AMO_LANGUAGES = (
    'af', 'ar', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'en-US', 'es-ES',
    'eu', 'fa', 'fi', 'fr', 'ga-IE', 'he', 'hu', 'id', 'it', 'ja', 'ko', 'mn',
    'nl', 'pl', 'pt-BR', 'pt-PT', 'ro', 'ru', 'sk', 'sq', 'sr', 'sv-SE',
    'uk', 'vi', 'zh-CN', 'zh-TW',
)

# Override Django's built-in with our native names
LANGUAGES = dict([(i.lower(), product_details.languages[i]['native'])
                 for i in AMO_LANGUAGES])
RTL_LANGUAGES = ('ar', 'fa', 'fa-IR', 'he')

LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])

TEXT_DOMAIN = 'z-messages'

TOWER_KEYWORDS = {
    '_lazy': None,
}

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

# Full URL to your API service. No trailing slash.
#   Example: https://services.addons.mozilla.org
SERVICES_URL = 'http://services.%s' % DOMAIN

OAUTH_CALLBACK_VIEW = 'api.views.request_token_ready'

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = path('media')

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = '/media//'

# Absolute path to a temporary storage area
TMP_PATH = path('tmp')

# Absolute path to a writable directory shared by all servers. No trailing
# slash.  Example: /data/
NETAPP_STORAGE = TMP_PATH

#  File path for storing XPI/JAR files (or any files associated with an
#  add-on). Example: /mnt/netapp_amo/addons.mozilla.org-remora/files
ADDONS_PATH = NETAPP_STORAGE + '/addons'

# Absolute path to a writable directory shared by all servers. No trailing
# slash.
# Example: /data/uploads
UPLOADS_PATH = NETAPP_STORAGE + '/uploads'

# URL prefix for admin media -- CSS, JavaScript and images. Make sure to use a
# trailing slash.
# Examples: "http://foo.com/media/", "/media/".
ADMIN_MEDIA_PREFIX = '/admin-media/'

# paths that don't require an app prefix
SUPPORTED_NONAPPS = ('admin', 'developers', 'editors', 'img',
                     'jsi18n', 'localizers', 'media', 'robots.txt',
                     'statistics', 'services')
DEFAULT_APP = 'firefox'

# paths that don't require a locale prefix
SUPPORTED_NONLOCALES = ('img', 'media', 'robots.txt', 'services', 'downloads')

# Make this unique, and don't share it with anybody.
SECRET_KEY = 'r#%9w^o_80)7f%!_ir5zx$tu3mupw9u%&s!)-_q%gy7i+fhx#)'

# Templates

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.load_template_source',
    'django.template.loaders.app_directories.load_template_source',
)

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.core.context_processors.auth',
    'django.core.context_processors.debug',
    'django.core.context_processors.media',
    'django.core.context_processors.request',
    'csrf_context.csrf',

    'django.contrib.messages.context_processors.messages',

    'amo.context_processors.app',
    'amo.context_processors.i18n',
    'amo.context_processors.global_settings',
    'jingo_minify.helpers.build_ids',
)

TEMPLATE_DIRS = (
    path('templates'),
)


def JINJA_CONFIG():
    import jinja2
    from django.conf import settings
    from caching.base import cache
    config = {'extensions': ['tower.template.i18n', 'amo.ext.cache',
                             'jinja2.ext.do',
                             'jinja2.ext.with_', 'jinja2.ext.loopcontrols'],
              'finalize': lambda x: x if x is not None else ''}
    if 'memcached' in cache.scheme and not settings.DEBUG:
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
    'amo.middleware.TimingMiddleware',
    'amo.middleware.LocaleAndAppURLMiddleware',
    'amo.middleware.RemoveSlashMiddleware',

    # Munging REMOTE_ADDR must come before ThreadRequest.
    'commonware.middleware.SetRemoteAddrFromForwardedFor',

    'commonware.middleware.FrameOptionsHeader',
    'commonware.log.ThreadRequestMiddleware',
    'multidb.middleware.PinningRouterMiddleware',

    'csp.middleware.CSPMiddleware',

    'amo.middleware.CommonMiddleware',
    'amo.middleware.NoVarySessionMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',

    'cake.middleware.CakeCookieMiddleware',
    'cake.middleware.CookieCleaningMiddleware',

    'amo.middleware.AdminMessageMiddleware',

    # This should come after authentication middleware
    'access.middleware.ACLMiddleware',

    'commonware.middleware.HidePasswordOnException',
)

# Auth
AUTHENTICATION_BACKENDS = (
    'users.backends.AmoUserBackend',
    'cake.backends.SessionBackend',
)
AUTH_PROFILE_MODULE = 'users.UserProfile'

ROOT_URLCONF = '%s.urls' % ROOT_PACKAGE

INSTALLED_APPS = (
    'amo',  # amo comes first so it always takes precedence.
    'access',
    'addons',
    'api',
    'applications',
    'bandwagon',
    'blocklist',
    'browse',
    'cronjobs',
    'csp',
    'devhub',
    'discovery',
    'editors',
    'extras',
    'files',
    'jingo_minify',
    'nick',
    'pages',
    'reviews',
    'search',
    'sharing',
    'stats',
    'tags',
    'tower',  # for ./manage.py extract
    'translations',
    'users',
    'versions',
    'zadmin',

    # We need this so the jsi18n view will pick up our locale directory.
    ROOT_PACKAGE,

    'cake',

    # Third party apps
    'djcelery',
    'django_nose',
    'piston',

    # Django contrib apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.messages',
    'django.contrib.sessions',
)

# These apps will be removed from INSTALLED_APPS in a production environment.
DEV_APPS = (
    'django_nose',
)

# Tests
TEST_RUNNER = 'test_utils.runner.RadicalTestSuiteRunner'

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
        ('**/templates/**.html',
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
        ('media/js/zamboni/**.js', 'javascript'),
    ],
}

# These domains will not be merged into z-keys.pot and will use separate PO
# files.
STANDALONE_DOMAINS = [
    'javascript',
    ]

# Bundles is a dictionary of two dictionaries, css and js, which list css files
# and js files that can be bundled together by the minify app.
MINIFY_BUNDLES = {
    'css': {
        # CSS files common to the entire site.
        'common': (
            'css/main.css',
            'css/main-mozilla.css',
            'css/jquery-lightbox.css',
            'css/autocomplete.css',
        ),
        'zamboni/z': (
            'css/zamboni/zamboni.css',
            'css/zamboni/tags.css',
            'css/zamboni/tabs.css',
        ),
        'zamboni/discovery-pane': (
            'css/zamboni/discovery-pane.css',
        ),
        'zamboni/devhub': (
            'css/zamboni/developers.css',
        ),
    },
    'js': {
        # JS files common to the entire site.
        'common': (
            'js/zamboni/jquery-1.4.2.min.js',
            'js/zamboni/jquery-ui/custom-1.8.5.min.js',
            'js/zamboni/underscore-min.js',
            'js/amo2009/addons.js',
            'js/zamboni/init.js',
            'js/zamboni/buttons.js',
            'js/zamboni/search.js',
            'js/zamboni/tabs.js',

            'js/jquery.cookie.js',
            'js/zamboni/global.js',
            'js/amo2009/global.js',
            'js/jquery-ui/jqModal.js',
            'js/amo2009/home.js',

            # Homepage
            'js/zamboni/homepage.js',

            # Add-ons details page
            'js/jquery-ui/ui.lightbox.js',
            'js/zamboni/tags.js',
            'js/get-satisfaction-v2.js',
            'js/zamboni/contributions.js',
            'js/zamboni/addon_details.js',
            'js/zamboni/reviews.js',

            # Personas
            'js/zamboni/jquery.hoverIntent.min.js',
            'js/zamboni/personas.js',

            # Collections
            'js/zamboni/collections.js',

            # Users
            'js/zamboni/users.js',
        ),
        'zamboni/discovery-pane': (
            'js/zamboni/jquery-1.4.2.min.js',
            'js/zamboni/discovery_pane.js',
        ),
        'zamboni/devhub': (
            'js/zamboni/truncation.js',
            'js/zamboni/devhub.js',
        ),
    }
}


# Caching
# Prefix for cache keys (will prevent collisions when running parallel copies)
CACHE_PREFIX = 'amo:%s:' % build_id
FETCH_BY_ID = True

# Number of seconds a count() query should be cached.  Keep it short because
# it's not possible to invalidate these queries.
CACHE_COUNT_TIMEOUT = 60

# External tools.
SPHINX_INDEXER = 'indexer'
SPHINX_SEARCHD = 'searchd'
SPHINX_CONFIG_PATH = path('configs/sphinx/sphinx.conf')
SPHINX_CATALOG_PATH = TMP_PATH + '/data/sphinx'
SPHINX_LOG_PATH = TMP_PATH + '/log/searchd'
SPHINX_HOST = '127.0.0.1'
SPHINX_PORT = 3312
SPHINXQL_PORT = 3307

TEST_SPHINX_PORT = 3412
TEST_SPHINXQL_PORT = 3407
TEST_SPHINX_CATALOG_PATH = TMP_PATH + '/test/data/sphinx'
TEST_SPHINX_LOG_PATH = TMP_PATH + '/test/log/searchd'

SPHINX_TIMEOUT = 1

JAVA_BIN = '/usr/bin/java'

# Mongo Settings
MONGO_HOST = 'localhost'
MONGO_PORT = 27017
MONGO_DATABASE = 'zamboni'
MONGO_USERNAME = None
MONGO_PASSWORD = None

# Add-on download settings.
MIRROR_DELAY = 30  # Minutes before we serve downloads from mirrors.
MIRROR_URL = 'http://releases.mozilla.org/pub/mozilla.org/addons'
LOCAL_MIRROR_URL = '%s/files' % SITE_URL

# File paths
ADDON_ICONS_PATH = UPLOADS_PATH + '/addon_icons'
COLLECTIONS_ICON_PATH = UPLOADS_PATH + '/collection_icons'
PREVIEWS_PATH = UPLOADS_PATH + '/previews'
USERPICS_PATH = UPLOADS_PATH + '/userpics'

# URL paths
# paths for images, e.g. mozcdn.com/amo or '/static'
STATIC_URL = SITE_URL
ADDON_ICON_URL = "%s/%s/%s/images/addon_icon/%%d/%%s" % (
        STATIC_URL, LANGUAGE_CODE, DEFAULT_APP)
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        '/img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (STATIC_URL +
        '/img/uploads/previews/full/%s/%d.png?modified=%d')
USERPICS_URL = STATIC_URL + '/img/uploads/userpics/%s/%s/%s.png?modified=%d'
# paths for uploaded extensions
FILES_URL = SITE_URL + "/%s/%s/downloads/file/%d/%s?src=%s"
COLLECTION_ICON_URL = ('%s/%s/%s/images/collection_icon/%%s/%%s' %
                       (STATIC_URL, LANGUAGE_CODE, DEFAULT_APP))
PERSONAS_IMAGE_URL = ('http://www.getpersonas.com/static/'
                      '%(tens)d/%(units)d/%(id)d/%(file)s')
PERSONAS_IMAGE_URL_SSL = ('https://www.getpersonas.com/static/'
                          '%(tens)d/%(units)d/%(id)d/%(file)s')
PERSONAS_USER_ROOT = 'http://www.getpersonas.com/gallery/designer/%s'

# Outgoing URL bouncer
REDIRECT_URL = 'http://outgoing.mozilla.org/v1/'
REDIRECT_SECRET_KEY = ''

# Default to short expiration; check "remember me" to override
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 1209600
SESSION_COOKIE_SECURE = True
MESSAGE_STORAGE = 'django.contrib.messages.storage.session.SessionStorage'

# These should have app+locale at the start to avoid redirects
LOGIN_URL = "/users/login"
LOGOUT_URL = "/users/logout"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# Legacy Settings
# used by old-style CSRF token
CAKE_SESSION_TIMEOUT = 8640

# PayPal Settings
PAYPAL_API_URL = 'https://api-3t.paypal.com/nvp'
PAYPAL_API_VERSION = '50'
PAYPAL_BN = ''
PAYPAL_CGI_URL = 'https://www.paypal.com/cgi-bin/webscr'
PAYPAL_PASSWORD = ''
PAYPAL_SIGNATURE = ''
PAYPAL_USER = ''

# Paypal is an awful place that doesn't understand locales.  Instead they have
# country codes.  This maps our locales to their codes.
PAYPAL_COUNTRYMAP = {
    'af': 'ZA', 'ar': 'EG', 'ca': 'ES', 'cs': 'CZ', 'cy': 'GB', 'da': 'DK',
    'de': 'DE', 'de-AT': 'AT', 'de-CH': 'CH', 'el': 'GR', 'en-GB': 'GB',
    'eu': 'BS', 'fa': 'IR', 'fi': 'FI', 'fr': 'FR', 'he': 'IL', 'hu': 'HU',
    'id': 'ID', 'it': 'IT', 'ja': 'JP', 'ko': 'KR', 'mn': 'MN', 'nl': 'NL',
    'pl': 'PL', 'ro': 'RO', 'ru': 'RU', 'sk': 'SK', 'sq': 'AL', 'sr': 'CS',
    'tr': 'TR', 'uk': 'UA', 'vi': 'VI',
}

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


## Celery
BROKER_HOST = 'localhost'
BROKER_PORT = 5672
BROKER_USER = 'zamboni'
BROKER_PASSWORD = 'zamboni'
BROKER_VHOST = 'zamboni'
BROKER_CONNECTION_TIMEOUT = 0.1
CELERY_RESULT_BACKEND = 'amqp'
CELERY_IGNORE_RESULT = True


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
# See PEP 391 and log_settings.py for formatting help.  Each section of LOGGING
# will get merged into the corresponding section of log_settings.py.
# Handlers and log levels are set up automatically based on LOG_LEVEL and DEBUG
# unless you set them here.  Messages will not propagate through a logger
# unless propagate: True is set.
LOGGING = {
    'loggers': {
        'amqplib': {'handlers': ['null']},
        'caching': {'handlers': ['null']},
        'suds': {'handlers': ['null']},
        'z.sphinx': {'level': logging.INFO},
        'z.task': {'level': logging.INFO},
    },
}

# CSP Settings
CSP_REPORT_URI = '/services/csp/report'
CSP_POLICY_URI = '/services/csp/policy'
CSP_REPORT_ONLY = True

CSP_ALLOW = ("'self'",)
CSP_IMG_SRC = ("'self'", STATIC_URL,
               "https://www.google.com",  # Recaptcha comes from google
               "https://statse.webtrendslive.com",
               "https://www.getpersonas.com",)
CSP_SCRIPT_SRC = ("'self'", STATIC_URL,
                  "https://api-secure.recaptcha.net",
                  "https://www.google.com",  # Recaptcha
                  )
CSP_STYLE_SRC = ("'self'", STATIC_URL,)
CSP_OBJECT_SRC = ("'none'",)
CSP_MEDIA_SRC = ("'none'",)
CSP_FRAME_SRC = ("'none'",)
CSP_FONT_SRC = ("'self'", "fonts.mozilla.com",)
CSP_FRAME_ANCESTORS = ("'none'",)  # We also send x-frame-options:DENY

# If you don't want experimental add-ons to show up in any search results or
# have detail pages, flip this switch
SANDBOX_PANIC = False

# Should robots.txt deny everything or disallow a calculated list of URLs we
# don't want to be crawled?  Default is false, disallow everything.
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
    env['AUTHENTICATION_BACKENDS'] = ()

    # Add in the read-only middleware before csrf middleware.
    extra = 'amo.middleware.ReadOnlyMiddleware'
    before = 'django.middleware.csrf.CsrfViewMiddleware'
    m = list(env['MIDDLEWARE_CLASSES'])
    m.insert(m.index(before), extra)
    env['MIDDLEWARE_CLASSES'] = tuple(m)


# Uploaded file limits
MAX_ICON_UPLOAD_SIZE = 4 * 1024 * 1024
MAX_PHOTO_UPLOAD_SIZE = MAX_ICON_UPLOAD_SIZE

# RECAPTCHA - copy all three statements to settings_local.py
RECAPTCHA_PUBLIC_KEY = ''
RECAPTCHA_PRIVATE_KEY = ''
RECAPTCHA_URL = ('https://api-secure.recaptcha.net/challenge?k=%s' %
                 RECAPTCHA_PUBLIC_KEY)

# Send Django signals asynchronously on a background thread.
ASYNC_SIGNALS = True

# Performance notes on add-ons
PERFORMANCE_NOTES = False
