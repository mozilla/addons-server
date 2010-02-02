# -*- coding: utf-8 -*-
# Django settings for zamboni project.

import os
import logging
import socket


# Make filepaths relative to settings.
ROOT = os.path.dirname(os.path.abspath(__file__))
path = lambda *a: os.path.join(ROOT, *a)

DEBUG = True
TEMPLATE_DEBUG = DEBUG
DEBUG_PROPAGATE_EXCEPTIONS = True

ADMINS = (
    # ('Your Name', 'your_email@domain.com'),
)

MANAGERS = ADMINS

DATABASES = {
    'default': {
        'NAME': 'zamboni',
        'ENGINE': 'django.db.backends.mysql',
        'HOST': '',
        'PORT': '',
        'USER': '',
        'PASSWORD': '',
        'OPTIONS': {'init_command': 'SET storage_engine=InnoDB'},
    },
}

DATABASE_ROUTERS = ('multidb.MasterSlaveRouter',)

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

# Accepted locales and apps
LANGUAGES = {
    'ar': u'عربي',
    'ca': u'català',
    'cs': u'Čeština',
    'da': u'Dansk',
    'de': u'Deutsch',
    'el': u'Ελληνικά',
    'en-US': u'English (US)',
    'es-ES': u'Español (de España)',
    'eu': u'Euskara',
    'fa': u'فارسی',
    'fi': u'suomi',
    'fr': u'Français',
    'ga-IE': u'Gaeilge',
    'he': u'עברית',
    'hu': u'Magyar',
    'id': u'Bahasa Indonesia',
    'it': u'Italiano',
    'ja': u'日本語',
    'ko': u'한국어',
    'mn': u'Монгол',
    'nl': u'Nederlands',
    'pl': u'Polski',
    'pt-BR': u'Português (do Brasil)',
    'pt-PT': u'Português (Europeu)',
    'ro': u'română',
    'ru': u'Русский',
    'sk': u'slovenčina',
    'sq': u'Shqip',
    'sv-SE': u'Svenska',
    'uk': u'Українська',
    'vi': u'Tiếng Việt',
    'zh-CN': u'中文 (简体)',
    'zh-TW': u'正體中文 (繁體)',
}

SITE_ID = 1

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = True

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = path('media')

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = '/media/'

# URL prefix for admin media -- CSS, JavaScript and images. Make sure to use a
# trailing slash.
# Examples: "http://foo.com/media/", "/media/".
ADMIN_MEDIA_PREFIX = '/admin-media/'

# Make this unique, and don't share it with anybody.
SECRET_KEY = 'r#%9w^o_80)7f%!_ir5zx$tu3mupw9u%&s!)-_q%gy7i+fhx#)'

# List of callables that know how to import templates from various sources.
TEMPLATE_LOADERS = (
    'django.template.loaders.filesystem.load_template_source',
    'django.template.loaders.app_directories.load_template_source',
)

MIDDLEWARE_CLASSES = (
    # AMO URL middleware comes first so everyone else sees nice URLs.
    'amo.middleware.LocaleAndAppURLMiddleware',

    'django.middleware.common.CommonMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',

    'cake.middleware.CakeCookieMiddleware',
    # This should come after authentication middle ware
    'access.middleware.ACLMiddleware',
)

AUTHENTICATION_BACKENDS = (
    'users.backends.AmoUserBackend',
    'cake.backends.SessionBackend',
)

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.core.context_processors.auth',
    'django.core.context_processors.debug',
    'django.core.context_processors.media',
    'django.core.context_processors.request',
    'django.core.context_processors.csrf',

    'amo.context_processors.i18n',
    'amo.context_processors.links',
)

ROOT_URLCONF = 'zamboni.urls'

TEMPLATE_DIRS = (
    path('templates'),
)

INSTALLED_APPS = (
    'amo',
    'access',
    'addons',
    'admin',
    'applications',
    'bandwagon',
    'blocklist',
    'devhub',
    'editors',
    'files',
    'reviews',
    'search',
    'tags',
    'translations',
    'users',
    'versions',

    'cake',
    'django_nose',

    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.sites',
)

# These apps will be removed from INSTALLED_APPS in a production environment.
DEV_APPS = (
    'django_nose',
)

TEST_RUNNER = 'test_utils.runner.RadicalTestSuiteRunner'

LOG_LEVEL = logging.DEBUG

# Full base URL for your main site including protocol.  No trailing slash.
#   Example: https://addons.mozilla.org
SITE_URL = 'http://%s' % socket.gethostname()

# If you want to run Selenium tests, you'll need to have a server running.
# Then give this a dictionary of settings.  Something like:
#    'HOST': 'localhost',
#    'PORT': 4444,
#    'BROWSER': '*firefox', # Alternative: *safari
SELENIUM_CONFIG = {}

# paths that don't require an app prefix
SUPPORTED_NONAPPS = ('admin', 'developers', 'editors', 'localizers',
                     'statistics',)
DEFAULT_APP = 'firefox'

# Length of time to store items in memcache
CACHE_DURATION = 60  # seconds

# Prefix for cache keys (will prevent collisions when running parallel copies)
CACHE_PREFIX = 'amo:'

AUTH_PROFILE_MODULE = 'users.UserProfile'

SPHINX_INDEXER = 'indexer'
SPHINX_SEARCHD = 'searchd'
SPHINX_CONFIG_PATH = path('configs/sphinx/sphinx.conf')
SPHINX_HOST = '127.0.0.1'
SPHINX_PORT = 3312
