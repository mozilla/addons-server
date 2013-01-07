import atexit
import tempfile

from django.utils.functional import lazy

_tmpdirs = set()


def _cleanup():
    try:
        import sys
        import shutil
    except ImportError:
        return
    tmp = None
    try:
        for tmp in _tmpdirs:
            shutil.rmtree(tmp)
    except Exception, exc:
        sys.stderr.write("\n** shutil.rmtree(%r): %s\n" % (tmp, exc))

atexit.register(_cleanup)


def _polite_tmpdir():
    tmp = tempfile.mkdtemp()
    _tmpdirs.add(tmp)
    return tmp

# See settings.py for documentation:
IN_TEST_SUITE = True
NETAPP_STORAGE = _polite_tmpdir()
ADDONS_PATH = _polite_tmpdir()
PERSONAS_PATH = _polite_tmpdir()
GUARDED_ADDONS_PATH = _polite_tmpdir()
WATERMARKED_ADDONS_PATH = _polite_tmpdir()
SIGNED_APPS_PATH = _polite_tmpdir()
SIGNED_APPS_REVIEWER_PATH = _polite_tmpdir()
UPLOADS_PATH = _polite_tmpdir()
MIRROR_STAGE_PATH = _polite_tmpdir()
TMP_PATH = _polite_tmpdir()
COLLECTIONS_ICON_PATH = _polite_tmpdir()
PACKAGER_PATH = _polite_tmpdir()

# We won't actually send an email.
SEND_REAL_EMAIL = True

# Turn off search engine indexing.
USE_ELASTIC = False

# Ensure all validation code runs in tests:
VALIDATE_ADDONS = True

PAYPAL_PERMISSIONS_URL = ''

STATIC_URL = ''
SITE_URL = ''
MOBILE_SITE_URL = ''
MEDIA_URL = '/media/'
# Reset these URLs to the defaults so your settings_local doesn't clobber them:
ADDON_ICONS_DEFAULT_URL = MEDIA_URL + '/img/addon-icons'
ADDON_ICON_BASE_URL = MEDIA_URL + 'img/icons/'
ADDON_ICON_URL = (
    STATIC_URL + '/img/uploads/addon_icons/%s/%s-%s.png?modified=%s')
PREVIEW_THUMBNAIL_URL = (
    STATIC_URL + '/img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (
    STATIC_URL + '/img/uploads/previews/full/%s/%d.%s?modified=%d')
USERPICS_URL = STATIC_URL + '/img/uploads/userpics/%s/%s/%s.png?modified=%d'

CACHES = {
    'default': {
        'BACKEND': 'caching.backends.locmem.CacheClass',
    }
}

# No more failures!
APP_PREVIEW = False

# Overrides whatever storage you might have put in local settings.
DEFAULT_FILE_STORAGE = 'amo.utils.LocalFileStorage'

VIDEO_LIBRARIES = ['lib.video.dummy']
INAPP_VERBOSE_ERRORS = False
INAPP_REQUIRE_HTTPS = True

ALLOW_SELF_REVIEWS = True

# Make sure debug toolbar output is disabled so it doesn't interfere with any
# html tests.


def custom_show_toolbar(request):
    return False

DEBUG_TOOLBAR_CONFIG = {
    'INTERCEPT_REDIRECTS': False,
    'SHOW_TOOLBAR_CALLBACK': custom_show_toolbar,
    'HIDE_DJANGO_SQL': True,
    'TAG': 'div',
    'ENABLE_STACKTRACES': False,
}

MOZMARKET_VENDOR_EXCLUDE = []

# These are the default languages. If you want a constrainted set for your
# tests, you should add those in the tests.


def lazy_langs(languages):
    from product_details import product_details
    if not product_details.languages:
        return {}
    return dict([(i.lower(), product_details.languages[i]['native'])
                 for i in languages])

AMO_LANGUAGES = (
    'af', 'ar', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'en-US', 'es', 'eu', 'fa',
    'fi', 'fr', 'ga-IE', 'he', 'hu', 'id', 'it', 'ja', 'ko', 'mn', 'nl', 'pl',
    'pt-BR', 'pt-PT', 'ro', 'ru', 'sk', 'sl', 'sq', 'sv-SE', 'uk', 'vi',
    'zh-CN', 'zh-TW',
)
LANGUAGES = lazy(lazy_langs, dict)(AMO_LANGUAGES)
LANGUAGE_URL_MAP = dict([(i.lower(), i) for i in AMO_LANGUAGES])
TASK_USER_ID = '4043307'

PASSWORD_HASHERS = (
    'django.contrib.auth.hashers.MD5PasswordHasher',
)

SQL_RESET_SEQUENCES = False
