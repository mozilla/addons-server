import re

from django.utils.translation import ugettext_lazy as _

from .base import (
    ADDON_DICT,
    ADDON_EXTENSION,
    ADDON_LPAPP,
    ADDON_PLUGIN,
    ADDON_STATICTHEME,
)

from olympia.versions.compare import version_int as vint


class App(object):
    @classmethod
    def matches_user_agent(cls, user_agent):
        return cls.user_agent_string in user_agent


# Applications
class FIREFOX(App):
    id = 1
    shortername = 'fx'
    short = 'firefox'
    pretty = _('Firefox')
    browser = True
    types = [ADDON_EXTENSION, ADDON_DICT, ADDON_LPAPP, ADDON_PLUGIN, ADDON_STATICTHEME]
    guid = '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}'
    min_display_version = 3.0
    # These versions were relabeled and should not be displayed.
    exclude_versions = (3.1, 3.7, 4.2)
    user_agent_string = 'Firefox'
    platforms = 'desktop'  # DESKTOP_PLATFORMS (set in constants.platforms)

    @classmethod
    def matches_user_agent(cls, user_agent):
        matches = cls.user_agent_string in user_agent
        if 'Android' in user_agent or 'Mobile' in user_agent or 'Tablet' in user_agent:
            matches = False
        return matches


class THUNDERBIRD(App):
    id = 18
    short = 'thunderbird'
    shortername = 'tb'
    pretty = _('Thunderbird')
    browser = False
    types = [ADDON_EXTENSION, ADDON_DICT, ADDON_LPAPP]
    guid = '{3550f703-e582-4d05-9a08-453d09bdfdc6}'
    min_display_version = 1.0
    user_agent_string = 'Thunderbird'
    platforms = 'desktop'  # DESKTOP_PLATFORMS (set in constants.platforms)


class SEAMONKEY(App):
    id = 59
    short = 'seamonkey'
    shortername = 'sm'
    pretty = _('SeaMonkey')
    browser = True
    types = [ADDON_EXTENSION, ADDON_DICT, ADDON_LPAPP, ADDON_PLUGIN]
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
    pretty = _('Sunbird')
    browser = False
    types = [ADDON_EXTENSION, ADDON_DICT, ADDON_LPAPP]
    guid = '{718e30fb-e89b-41dd-9da7-e25a45638b28}'
    min_display_version = 0.2
    latest_version = None
    user_agent_string = 'Sunbird'
    platforms = 'desktop'  # DESKTOP_PLATFORMS (set in constants.platforms)


class MOBILE(App):
    """Old Firefox for Mobile.

    Not supported anymore, should not be added to APPS."""

    id = 60
    short = 'mobile'
    shortername = 'fn'
    pretty = _('Mobile')
    browser = True
    types = [ADDON_EXTENSION, ADDON_DICT, ADDON_LPAPP]
    guid = '{a23983c0-fd0e-11dc-95ff-0800200c9a66}'
    min_display_version = 0.1
    user_agent_string = 'Fennec'
    platforms = 'mobile'  # DESKTOP_PLATFORMS (set in constants.platforms)


class ANDROID(App):
    # This is for the Android native Firefox.
    id = 61
    short = 'android'
    shortername = 'an'
    pretty = _('Firefox for Android')
    browser = True
    types = [ADDON_EXTENSION, ADDON_DICT, ADDON_LPAPP]
    guid = '{aa3c5121-dab2-40e2-81ca-7ea25febc110}'
    min_display_version = 11.0
    user_agent_string = 'Fennec'
    # Mobile and Android have the same user agent. The only way to distinguish
    # is by the version number.
    user_agent_re = [
        re.compile(r'Fennec/([\d.]+)'),
        re.compile(r'Android; Mobile; rv:([\d.]+)'),
        re.compile(r'Android; Tablet; rv:([\d.]+)'),
        re.compile(r'Mobile; rv:([\d.]+)'),
        re.compile(r'Tablet; rv:([\d.]+)'),
    ]
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
    pretty = _('Mozilla')
    browser = True
    types = [ADDON_EXTENSION, ADDON_DICT, ADDON_LPAPP, ADDON_PLUGIN]
    guid = '{86c18b42-e466-45a9-ae7a-9b95ba6f5640}'
    platforms = 'desktop'  # DESKTOP_PLATFORMS (set in constants.platforms)


class UNKNOWN_APP(App):
    """Placeholder for unknown applications."""

    pretty = _('Unknown')


# UAs will attempt to match in this order.
APP_DETECT = (ANDROID, FIREFOX)
APP_USAGE = (FIREFOX, ANDROID)
APPS = {app.short: app for app in APP_USAGE}
APP_OBSOLETE = (MOZILLA, SUNBIRD, MOBILE, THUNDERBIRD, SEAMONKEY)
APPS_ALL = {app.id: app for app in APP_USAGE + APP_OBSOLETE}
APP_IDS = {app.id: app for app in APP_USAGE}
APP_GUIDS = {app.guid: app for app in APP_USAGE}
APPS_CHOICES = tuple((app.id, app.pretty) for app in APP_USAGE)

APP_TYPE_SUPPORT = {}
for _app in APP_USAGE:
    for _type in _app.types:
        APP_TYPE_SUPPORT.setdefault(_type, []).append(_app)

# Fake max version for when we want max compatibility
FAKE_MAX_VERSION = '65535'

# The lowest maxVersion an app has to support to allow default-to-compatible.
D2C_MIN_VERSIONS = {
    FIREFOX.id: '4.0',
    ANDROID.id: '11.0',
}

for _app in APPS_ALL.values():
    _versions = list(getattr(_app, 'exclude_versions', []))
    _versions.append(FAKE_MAX_VERSION)
    _app.exclude_versions = tuple(_versions)

del _app, _type, _versions
