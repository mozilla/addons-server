DATABASE_SETTINGS = {
      'db': '',
      'user': '',
      'passwd': '',
      'host': ''}

MIRROR_DELAY = 30  # Minutes before we serve downloads from mirrors.
MIRROR_URL = 'http://releases.mozilla.org/pub/mozilla.org/addons'
LOCAL_MIRROR_URL = 'https://static.addons.mozilla.net/_files'
PRIVATE_MIRROR_URL = '/_privatefiles'

DEBUG = False

SITE_URL = 'http://addons.mozilla.local:8000'

try:
    from settings_services_local import *
except ImportError:
    pass
