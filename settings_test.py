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
MEDIA_ROOT = _polite_tmpdir()
TMP_PATH = _polite_tmpdir()

# Don't call out to persona in tests.
AUTHENTICATION_BACKENDS = (
    'users.backends.AmoUserBackend',
)

# We won't actually send an email.
SEND_REAL_EMAIL = True

# Turn off search engine indexing.
USE_ELASTIC = False

# Ensure all validation code runs in tests:
VALIDATE_ADDONS = True

PAYPAL_PERMISSIONS_URL = ''

ENABLE_API_ERROR_SERVICE = False

SITE_URL = 'http://testserver'
LOCAL_MIRROR_URL = SITE_URL
MOBILE_SITE_URL = ''

CACHES = {
    'default': {
        'BACKEND': 'caching.backends.locmem.LocMemCache',
    }
}

# COUNT() caching can't be invalidated, it just expires after x seconds. This
# is just too annoying for tests, so disable it.
CACHE_COUNT_TIMEOUT = -1

# Overrides whatever storage you might have put in local settings.
DEFAULT_FILE_STORAGE = 'amo.utils.LocalFileStorage'

VIDEO_LIBRARIES = ['lib.video.dummy']

ALLOW_SELF_REVIEWS = True

# Make sure debug toolbar output is disabled so it doesn't interfere with any
# html tests.


DEBUG_TOOLBAR_CONFIG = {
    'INTERCEPT_REDIRECTS': False,
    'SHOW_TOOLBAR_CALLBACK': lambda r: False,
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
    'users.models.SHA512PasswordHasher',
)

SQL_RESET_SEQUENCES = False

ES_DEFAULT_NUM_REPLICAS = 0
ES_DEFAULT_NUM_SHARDS = 3

# Ensure that exceptions aren't re-raised.
DEBUG_PROPAGATE_EXCEPTIONS = False
