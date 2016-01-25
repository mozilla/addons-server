# To enable the Django Debug Toolbar for local dev add the following line to
# your local_settings.py file:
# from djdt_settings import *

from settings import *  # noqa

INSTALLED_APPS += (
    'debug_toolbar',
)
DEBUG_TOOLBAR_PATCH_SETTINGS = False  # Prevent DDT from patching the settings.

MIDDLEWARE_CLASSES += ('debug_toolbar.middleware.DebugToolbarMiddleware',)


def debug_toolbar_enabled(request):
    """Callback used by the Django Debug Toolbar to decide when to display."""
    # We want to make sure to have the DEBUG value at runtime, not the one we
    # have in this specific settings file.
    from django.conf import settings
    return settings.DEBUG


DEBUG_TOOLBAR_CONFIG = {
    'SHOW_TOOLBAR_CALLBACK': 'settings.debug_toolbar_enabled',
    'JQUERY_URL': '',  # Use the jquery that's already on the page.
}


# Disable CSP by setting it as report only. We can't enable it because it uses
# "data:" for its logo, and it uses "unsafe eval" for some panels like the
# templates or SQL ones.
CSP_REPORT_ONLY = True
