from versions.compare import version_int as vint
from tower import ugettext_lazy as _

from base import *


class App:
    @classmethod
    def matches_user_agent(cls, user_agent):
        return cls.user_agent_string in user_agent


# Applications
class FIREFOX(App):
    id = 1
    shortername = 'fx'
    short = 'firefox'
    pretty = _(u'Firefox')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP, ADDON_PLUGIN, ADDON_PERSONA, ADDON_WEBAPP]
    guid = '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}'
    min_display_version = 3.0
    # These versions were relabeled and should not be displayed.
    exclude_versions = (3.1, 3.7, 4.2)
    backup_version = vint('3.7.*')
    user_agent_string = 'Firefox'
    platforms = 'desktop'  # DESKTOP_PLATFORMS (set in constants.platforms)

    @classmethod
    def matches_user_agent(cls, user_agent):
        matches = cls.user_agent_string in user_agent
        if 'Android' in user_agent or 'Mobile' in user_agent:
            matches = False
        return matches


class THUNDERBIRD(App):
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
    platforms = 'desktop'  # DESKTOP_PLATFORMS (set in constants.platforms)


class SEAMONKEY(App):
    id = 59
    short = 'seamonkey'
    shortername = 'sm'
    pretty = _(u'SeaMonkey')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP, ADDON_PLUGIN, ADDON_PERSONA]
    guid = '{92650c4d-4b8e-4d2a-b7eb-24ecf4f6b63a}'
    min_display_version = 1.0
    exclude_versions = (1.5,)
    latest_version = None
    user_agent_string = 'SeaMonkey'
    platforms = 'desktop'  # DESKTOP_PLATFORMS (set in constants.platforms)


class SUNBIRD(App):
    """This application is retired and should not be used on the site.  It
    remains as there are still some sunbird add-ons in the db."""
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
    platforms = 'desktop'  # DESKTOP_PLATFORMS (set in constants.platforms)


class MOBILE(App):
    id = 60
    short = 'mobile'
    shortername = 'fn'
    pretty = _(u'Mobile')
    browser = True
    types = [ADDON_EXTENSION, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP, ADDON_PERSONA]
    guid = '{a23983c0-fd0e-11dc-95ff-0800200c9a66}'
    min_display_version = 0.1
    user_agent_string = 'Fennec'
    platforms = 'mobile'  # DESKTOP_PLATFORMS (set in constants.platforms)


class ANDROID(App):
    # This is for the Android native Firefox.
    id = 61
    short = 'android'
    shortername = 'an'
    pretty = _(u'Android')
    browser = True
    types = [ADDON_EXTENSION, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP, ADDON_PERSONA]
    guid = '{aa3c5121-dab2-40e2-81ca-7ea25febc110}'
    min_display_version = 11.0
    user_agent_string = 'Fennec'
    # Mobile and Android have the same user agent. The only way to distinguish
    # is by the version number.
    user_agent_re = [re.compile('Fennec/([\d.]+)'),
                     re.compile('Android; Mobile; rv:([\d.]+)')]
    platforms = 'mobile'
    latest_version = None

    @classmethod
    def matches_user_agent(cls, user_agent):
        for user_agent_re in cls.user_agent_re:
            match = user_agent_re.search(user_agent)
            if match:
                v = match.groups()[0]
                return vint(cls.min_display_version) <= vint(v)


class MOZILLA(App):
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
    platforms = 'desktop'  # DESKTOP_PLATFORMS (set in constants.platforms)


class UNKNOWN_APP(App):
    """Placeholder for unknown applications."""
    pretty = _(u'Unknown')


class DEVICE_DESKTOP(object):
    id = 1
    name = _(u'Desktop')
    class_name = 'desktop'


class DEVICE_MOBILE(object):
    id = 2
    name = _(u'Mobile')
    class_name = 'mobile'


class DEVICE_TABLET(object):
    id = 3
    name = _(u'Tablet')
    class_name = 'tablet'


DEVICE_TYPES = {
    DEVICE_DESKTOP.id: DEVICE_DESKTOP,
    DEVICE_MOBILE.id: DEVICE_MOBILE,
    DEVICE_TABLET.id: DEVICE_TABLET,
}


# UAs will attempt to match in this order.
APP_DETECT = (ANDROID, MOBILE, THUNDERBIRD, SEAMONKEY, FIREFOX)
APP_USAGE = _apps = (FIREFOX, THUNDERBIRD, ANDROID, MOBILE, SEAMONKEY)
APPS = dict((app.short, app) for app in _apps)

APPS_ALL = dict((app.id, app) for app in _apps + (MOZILLA, SUNBIRD))
APP_IDS = dict((app.id, app) for app in _apps)
APP_GUIDS = dict((app.guid, app) for app in _apps)
APPS_RETIRED = dict([(MOZILLA.short, MOZILLA), (SUNBIRD.short, SUNBIRD)])

APP_TYPE_SUPPORT = {}
for _app in APP_USAGE:
    for _type in _app.types:
        APP_TYPE_SUPPORT.setdefault(_type, []).append(_app)

# The lowest maxVersion an app has to support to allow default-to-compatible.
D2C_MAX_VERSIONS = {
    FIREFOX.id: '4.0',
    MOBILE.id: '11.0',
    SEAMONKEY.id: '2.1',
    THUNDERBIRD.id: '5.0',
}

for _app in APPS_ALL.values():
    _versions = list(getattr(_app, 'exclude_versions', []))
    # 99 comes from the hacks we do to make search tools compatible with
    # versions (bug 692360).
    _versions.append(99)
    _app.exclude_versions = tuple(_versions)

del _app, _type
