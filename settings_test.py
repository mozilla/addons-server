from settings import *  # noqa

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

# Make sure the app needed to test translations is present.
INSTALLED_APPS += TEST_INSTALLED_APPS

# Make sure our initialization code gets loaded before any other apps.
#
# Since ordinary runs currently load this module from `manage.py`, it would
# be nice to load it from `conftest.py` in tests, for symmetry. Unfortunately,
# the `conftest.py` does not reliably load early enough for our setup to have
# any effect.
#
# In particular, pytest-django will load our settings module and initialize
# django immediately well before our own `conftest.py` file is even collected,
# if it already has a `DJANGO_SETTINGS_MODULE` environment variable or config
# setting at that point. When using pytest-xdist to split the tests into
# multiple, parallel processes, that variable is always set when worker
# processes are forked, so those processes will always initialize django
# before we would otherwise have a chance to configure it.
INSTALLED_APPS = ('setup_olympia',) + INSTALLED_APPS

# See settings.py for documentation:
IN_TEST_SUITE = True
MEDIA_ROOT = _polite_tmpdir()
TMP_PATH = _polite_tmpdir()

# Don't call out to persona in tests.
AUTHENTICATION_BACKENDS = (
    'users.backends.AmoUserBackend',
)

CELERY_ALWAYS_EAGER = True
DEBUG = False
TEMPLATE_DEBUG = False

# We won't actually send an email.
SEND_REAL_EMAIL = True

# Turn off search engine indexing.
USE_ELASTIC = False

# Ensure all validation code runs in tests:
VALIDATE_ADDONS = True

PAYPAL_PERMISSIONS_URL = ''

ENABLE_API_ERROR_SERVICE = False

SITE_URL = 'http://testserver'
MOBILE_SITE_URL = ''

# COUNT() caching can't be invalidated, it just expires after x seconds. This
# is just too annoying for tests, so disable it.
CACHE_COUNT_TIMEOUT = -1

# We don't want to share cache state between processes. Always use the local
# memcache backend for tests.
#
# Note: Per settings.py, this module can cause deadlocks when running as a web
# server. It's safe to use in tests, since we don't use threads, and there's
# no opportunity for contention, but it shouldn't be used in the base settings
# until we're sure the deadlock issues are fixed.
CACHES = {
    'default': {
        'BACKEND': 'caching.backends.locmem.LocMemCache',
        'LOCATION': 'olympia',
    }
}

# Overrides whatever storage you might have put in local settings.
DEFAULT_FILE_STORAGE = 'amo.utils.LocalFileStorage'

VIDEO_LIBRARIES = ['lib.video.dummy']

ALLOW_SELF_REVIEWS = True

# Make sure the debug toolbar isn't used during the tests.
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'debug_toolbar']

MOZMARKET_VENDOR_EXCLUDE = []

# These are the default languages. If you want a constrainted set for your
# tests, you should add those in the tests.


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

# Set to True if we're allowed to use X-SENDFILE.
XSENDFILE = True

# Don't enable the signing by default in tests, many would fail trying to sign
# empty or bad zip files, or try posting to the endpoints. We don't want that.
SIGNING_SERVER = ''
PRELIMINARY_SIGNING_SERVER = ''

###############################################################################
# Only if running on a CI server.
###############################################################################

if os.environ.get('RUNNING_IN_CI'):
    import product_details

    LOG_LEVEL = logging.ERROR

    class MockProductDetails:
        """Main information we need in tests.

        We don't want to rely on the product_details that are automatically
        downloaded in manage.py for the tests. Also, downloading all the
        information is very long, and we don't want that for each test build on
        travis for example.

        So here's a Mock that can be used instead of the real product_details.

        """
        last_update = False
        languages = dict((lang, {'native': lang}) for lang in AMO_LANGUAGES)
        firefox_versions = {"LATEST_FIREFOX_VERSION": "33.1.1"}
        thunderbird_versions = {"LATEST_THUNDERBIRD_VERSION": "31.2.0"}
        firefox_history_major_releases = {'1.0': '2004-11-09'}

        def __init__(self):
            """Some tests need specifics languages.

            This is an excerpt of lib/product_json/languages.json.

            """
            self.languages.update({
                u'el': {
                    u'native':
                        u'\u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac',
                    u'English': u'Greek'},
                u'hr': {
                    u'native': u'Hrvatski',
                    u'English': u'Croatian'},
                u'sr': {
                    u'native': u'\u0421\u0440\u043f\u0441\u043a\u0438',
                    u'English': u'Serbian'},
                u'en-US': {
                    u'native': u'English (US)',
                    u'English': u'English (US)'},
                u'tr': {
                    u'native': u'T\xfcrk\xe7e',
                    u'English': u'Turkish'},
                u'cy': {
                    u'native': u'Cymraeg',
                    u'English': u'Welsh'},
                u'sr-Latn': {
                    u'native': u'Srpski',
                    u'English': u'Serbian'}})

    product_details.product_details = MockProductDetails()
