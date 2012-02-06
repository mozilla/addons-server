import atexit
import tempfile


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
NETAPP_STORAGE = _polite_tmpdir()
ADDONS_PATH = _polite_tmpdir()
PERSONAS_PATH = _polite_tmpdir()
GUARDED_ADDONS_PATH = _polite_tmpdir()
WATERMARKED_ADDONS_PATH = _polite_tmpdir()
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
ADDON_ICON_URL = ('%s/images/addon_icon/%%d-%%d.png?modified=%%s' %
                  STATIC_URL)
PREVIEW_THUMBNAIL_URL = (STATIC_URL +
        '/img/uploads/previews/thumbs/%s/%d.png?modified=%d')
PREVIEW_FULL_URL = (STATIC_URL +
        '/img/uploads/previews/full/%s/%d.png?modified=%d')
USERPICS_URL = STATIC_URL + '/img/uploads/userpics/%s/%s/%s.png?modified=%d'

CACHE_BACKEND = 'caching.backends.locmem://'

# No more failures!
APP_PREVIEW = False

# Overrides whatever storage you might have put in local settings.
DEFAULT_FILE_STORAGE = 'amo.utils.LocalFileStorage'
