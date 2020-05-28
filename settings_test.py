# -*- coding: utf-8 -*-
from settings import *  # noqa


# Make sure the apps needed to test translations and core are present.
INSTALLED_APPS += (
    'olympia.translations.tests.testapp',
    'olympia.core.tests.db_tests_testapp',
)
# Make sure the debug toolbar isn't used during the tests.
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'debug_toolbar']
MIDDLEWARE = tuple(
    middleware for middleware in MIDDLEWARE
    if middleware != 'debug_toolbar.middleware.DebugToolbarMiddleware'
)

INTERNAL_ROUTES_ALLOWED = env('INTERNAL_ROUTES_ALLOWED', default=False)

# See settings.py for documentation:
IN_TEST_SUITE = True

# Don't call out to persona in tests.
AUTHENTICATION_BACKENDS = (
    'olympia.users.backends.TestUserBackend',
)

DEBUG = False

# We won't actually send an email.
SEND_REAL_EMAIL = True

SITE_URL = CDN_HOST = EXTERNAL_SITE_URL = 'http://testserver'

STATIC_URL = '%s/static/' % CDN_HOST
MEDIA_URL = '%s/user-media/' % CDN_HOST

# We are setting memcached here to make sure our test setup is as close
# to our production system as possible.
CACHES = {
    'default': {
        # `CacheStatTracker` is required for `assert_cache_requests` to work
        # properly
        'BACKEND': 'olympia.lib.cache.CacheStatTracker',
        'LOCATION': os.environ.get('MEMCACHE_LOCATION', 'localhost:11211'),
        'OPTIONS': {
            'ACTUAL_BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',  # noqa
        }
    },
}

# Overrides whatever storage you might have put in local settings.
DEFAULT_FILE_STORAGE = 'olympia.amo.utils.LocalFileStorage'

TASK_USER_ID = 1337

# Make sure we have no replicas and only one shard to allow for impedent
# search scoring
ES_DEFAULT_NUM_REPLICAS = 0
ES_DEFAULT_NUM_SHARDS = 1

# Don't enable the signing by default in tests, many would fail trying to sign
# empty or bad zip files, or try posting to the endpoints. We don't want that.
SIGNING_SERVER = ''

# Disable addon signing for unittests, too many would fail trying to sign
# corrupt/bad zip files. These will be enabled explicitly for unittests.
ENABLE_ADDON_SIGNING = False

# Limit logging in tests.
LOGGING['loggers'] = {
    '': {
        'handlers': ['null'],
        'level': logging.DEBUG,
        'propogate': False,
    },
    # Need to disable celery logging explicitly. Celery configures it's
    # logging manually and we don't catch their logger in our default config.
    'celery': {
        'handlers': ['null'],
        'level': logging.DEBUG,
        'propagate': False
    },
}

# To speed tests up, crushing uploaded images is disabled in tests except
# where we explicitly want to test pngcrush.
PNGCRUSH_BIN = '/bin/true'

BASKET_API_KEY = 'testkey'

# By default all tests are run in always-eager mode. Use `CeleryWorkerTestCase`
# to start an actual celery worker instead.
CELERY_TASK_ALWAYS_EAGER = True

CELERY_IMPORTS += (
    'olympia.amo.tests.test_celery',
    'olympia.lib.es.tests.test_commands',
)

CELERY_TASK_ROUTES.update({
    # Test tasks that will never really be triggered in prod.
    'olympia.amo.tests.test_celery.fake_task': {'queue': 'amo'},
    'olympia.amo.tests.test_celery.fake_task_with_result': {'queue': 'amo'},
    'olympia.amo.tests.test_celery.sleeping_task': {'queue': 'amo'},
    'olympia.lib.es.tests.test_commands.dummy_task': {'queue': 'amo'},
})
