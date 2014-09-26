from default.settings import *  # noqa

# To activate the Django debug toolbar.
INSTALLED_APPS += (
    'debug_toolbar',
    'fixture_magic',
)
DEBUG_TOOLBAR_PATCH_SETTINGS = False  # Prevent DDT from patching the settings.

INTERNAL_IPS = ('127.0.0.1',)
MIDDLEWARE_CLASSES += ('debug_toolbar.middleware.DebugToolbarMiddleware',)

# RUN_ES_TESTS = True  # Uncomment to run ES tests (Elasticsearch need
                       # to be installed).
