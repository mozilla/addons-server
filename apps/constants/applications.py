from versions.compare import version_int
from tower import ugettext_lazy as _

from base import *

# Applications
class FIREFOX:
    id = 1
    shortername = 'fx'
    short = 'firefox'
    pretty = _(u'Firefox')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP, ADDON_PLUGIN, ADDON_PERSONA]
    guid = '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}'
    min_display_version = 3.0
    # These versions were relabeled and should not be displayed.
    exclude_versions = (3.1, 3.7)
    backup_version = version_int('3.7.*')
    user_agent_string = 'Firefox'


class THUNDERBIRD:
    id = 18
    short = 'thunderbird'
    shortername = 'tb'
    pretty = _(u'Thunderbird')
    browser = False
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_LPAPP,
             ADDON_PERSONA]
    guid = '{3550f703-e582-4d05-9a08-453d09bdfdc6}'
    min_display_version = 1.0
    user_agent_string = 'Thunderbird'


class SEAMONKEY:
    id = 59
    short = 'seamonkey'
    shortername = 'sm'
    pretty = _(u'SeaMonkey')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP, ADDON_PLUGIN]
    guid = '{92650c4d-4b8e-4d2a-b7eb-24ecf4f6b63a}'
    min_display_version = 1.0
    exclude_versions = (1.5,)
    latest_version = None
    user_agent_string = 'SeaMonkey'


class SUNBIRD:
    id = 52
    short = 'sunbird'
    shortername = 'sb'
    pretty = _(u'Sunbird')
    browser = False
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_LPAPP]
    guid = '{718e30fb-e89b-41dd-9da7-e25a45638b28}'
    min_display_version = 0.2
    latest_version = None
    user_agent_string = 'Sunbird'


class MOBILE:
    id = 60
    short = 'mobile'
    shortername = 'fn'
    pretty = _(u'Mobile')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP]
    guid = '{a23983c0-fd0e-11dc-95ff-0800200c9a66}'
    min_display_version = 0.1
    latest_version = None
    user_agent_string = 'Fennec'


class MOZILLA:
    """Mozilla exists for completeness and historical purposes.

    Stats and other modules may reference this for history.
    This should NOT be added to APPS.
    """
    id = 2
    short = 'mz'
    shortername = 'mz'
    pretty = _(u'Mozilla')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP, ADDON_PLUGIN]
    guid = '{86c18b42-e466-45a9-ae7a-9b95ba6f5640}'

# UAs will attempt to match in this order
APP_DETECT = (MOBILE, THUNDERBIRD, SEAMONKEY, SUNBIRD, FIREFOX)
APP_USAGE = _apps = (FIREFOX, THUNDERBIRD, MOBILE, SEAMONKEY, SUNBIRD)
APPS = dict((app.short, app) for app in _apps)
APP_IDS = dict((app.id, app) for app in _apps)
APP_GUIDS = dict((app.guid, app) for app in _apps)
APPS_RETIRED = dict([(MOZILLA.short, MOZILLA)])
APPS_ALL = dict((app.id, app) for app in _apps + (MOZILLA,))

APP_TYPE_SUPPORT = {}
for _app in APP_USAGE:
    for _type in _app.types:
        APP_TYPE_SUPPORT.setdefault(_type, []).append(_app)
del _app, _type
