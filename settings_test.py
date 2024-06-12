# -*- coding: utf-8 -*-
# ruff: noqa: F405
from settings import *  # noqa


# Make sure the apps needed to test translations and core are present.
INSTALLED_APPS += (
    'olympia.translations.tests.testapp',
    'olympia.core.tests.db_tests_testapp',
    'olympia.core.tests.m2m_testapp',
)
# Make sure the debug toolbar isn't used during the tests.
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'debug_toolbar']
MIDDLEWARE = tuple(
    middleware
    for middleware in MIDDLEWARE
    if middleware != 'debug_toolbar.middleware.DebugToolbarMiddleware'
)

INTERNAL_ROUTES_ALLOWED = env('INTERNAL_ROUTES_ALLOWED', default=False)

# See settings.py for documentation:
IN_TEST_SUITE = True

DEBUG = False

# We won't actually send an email.
SEND_REAL_EMAIL = True

SITE_URL = EXTERNAL_SITE_URL = 'http://testserver'
INTERNAL_SITE_URL = 'http://testserver'

STATIC_URL = '%s/static/' % SITE_URL
MEDIA_URL = '%s/user-media/' % SITE_URL

# Tests run with DEBUG=False but we don't want to have to run collectstatic
# everytime, so reset STATICFILES_STORAGE to the default instead of
# ManifestStaticFilesStorage
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'

# Overrides whatever storage you might have put in local settings.
DEFAULT_FILE_STORAGE = 'olympia.amo.utils.SafeStorage'

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
LOGGING['root']['handlers'] = ['null']
for logger in list(LOGGING['loggers'].keys()):
    LOGGING['loggers'][logger]['handlers'] = ['null']
# Need to disable celery logging explicitly. Celery configures its logging
# manually and we don't catch their logger in our default config.
LOGGING['loggers']['celery'] = {
    'handlers': ['null'],
    'level': logging.DEBUG,
    'propagate': False,
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
    'olympia.search.tests.test_commands',
)

CELERY_TASK_ROUTES.update(
    {
        # Test tasks that will never really be triggered in prod.
        'olympia.amo.tests.test_celery.fake_task': {'queue': 'amo'},
        'olympia.amo.tests.test_celery.fake_task_with_result': {'queue': 'amo'},
        'olympia.amo.tests.test_celery.sleeping_task': {'queue': 'amo'},
        'olympia.search.tests.test_commands.dummy_task': {'queue': 'amo'},
        'olympia.devhub.tests.test_tasks.fake_task': {'queue': 'amo'},
    }
)

# switch cached_db out for just cache sessions to avoid extra db queries
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'

ADDONS_FRONTEND_PROXY_PORT = None

VERIFY_FXA_ACCESS_TOKEN = False

CINDER_API_TOKEN = 'fake-test-token'
CINDER_QUEUE_PREFIX = 'amo-env-'

SOCKET_LABS_TOKEN = 'fake-test-token'
SOCKET_LABS_SERVER_ID = '12345'
SOCKET_LABS_HOST = 'https://fake-socketlabs.com/v1/'
