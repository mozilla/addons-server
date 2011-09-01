from django.utils.datastructures import SortedDict

from tower import ugettext_lazy as _

from . import applications


# Platforms
class PLATFORM_ANY:
    id = 0
    name = _(u'Any')
    shortname = 'any'
    # API name is not translated
    api_name = u'ALL'


class PLATFORM_ALL:
    id = 1
    name = _(u'All Platforms')
    shortname = 'all'
    api_name = u'ALL'


class PLATFORM_ALL_MOBILE:
    id = 9
    name = _(u'All Mobile Platforms')
    shortname = 'allmobile'
    api_name = u'ALL_mobile'


class PLATFORM_LINUX:
    id = 2
    name = _(u'Linux')
    shortname = 'linux'
    api_name = u'Linux'


class PLATFORM_MAC:
    id = 3
    name = _(u'Mac OS X')
    shortname = 'mac'
    api_name = u'Darwin'


class PLATFORM_BSD:
    id = 4
    name = _(u'BSD')
    shortname = 'bsd'
    api_name = u'BSD_OS'


class PLATFORM_WIN:
    id = 5
    name = _(u'Windows')
    shortname = 'windows'
    api_name = u'WINNT'


class PLATFORM_SUN:
    id = 6
    name = _(u'Solaris')
    shortname = 'solaris'
    api_name = 'SunOS'


class PLATFORM_ANDROID:
    id = 7
    name = _(u'Android')
    shortname = u'android'
    api_name = u'Android'


class PLATFORM_MAEMO:
    id = 8
    name = _(u'Maemo')
    shortname = u'maemo'
    api_name = u'Maemo'

# Contains historic platforms that are no longer supported.
# These exist so that legacy files can still be edited.
PLATFORMS = {PLATFORM_ANY.id: PLATFORM_ANY, PLATFORM_ALL.id: PLATFORM_ALL,
             PLATFORM_LINUX.id: PLATFORM_LINUX, PLATFORM_MAC.id: PLATFORM_MAC,
             PLATFORM_BSD.id: PLATFORM_BSD, PLATFORM_WIN.id: PLATFORM_WIN,
             PLATFORM_SUN.id: PLATFORM_SUN,
             PLATFORM_ALL_MOBILE.id: PLATFORM_ALL_MOBILE,
             PLATFORM_ANDROID.id: PLATFORM_ANDROID,
             PLATFORM_MAEMO.id: PLATFORM_MAEMO}

MOBILE_PLATFORMS = SortedDict([(PLATFORM_ALL_MOBILE.id, PLATFORM_ALL_MOBILE),
                               (PLATFORM_ANDROID.id, PLATFORM_ANDROID),
                               (PLATFORM_MAEMO.id, PLATFORM_MAEMO)])

DESKTOP_PLATFORMS = SortedDict([(PLATFORM_ALL.id, PLATFORM_ALL),
                                (PLATFORM_LINUX.id, PLATFORM_LINUX),
                                (PLATFORM_MAC.id, PLATFORM_MAC),
                                (PLATFORM_WIN.id, PLATFORM_WIN)])

SUPPORTED_PLATFORMS = DESKTOP_PLATFORMS.copy()
SUPPORTED_PLATFORMS.update(MOBILE_PLATFORMS)

PLATFORM_DICT = {
    'all': PLATFORM_ALL,
    'linux': PLATFORM_LINUX,
    'mac': PLATFORM_MAC,
    'macosx': PLATFORM_MAC,
    'darwin': PLATFORM_MAC,
    'bsd': PLATFORM_BSD,
    'bsd_os': PLATFORM_BSD,
    'freebsd': PLATFORM_BSD,
    'win': PLATFORM_WIN,
    'winnt': PLATFORM_WIN,
    'windows': PLATFORM_WIN,
    'sun': PLATFORM_SUN,
    'sunos': PLATFORM_SUN,
    'solaris': PLATFORM_SUN,
    'mobile': PLATFORM_ALL_MOBILE,
    'android': PLATFORM_ANDROID,
    'maemo': PLATFORM_MAEMO,
}

_platforms = {'desktop': DESKTOP_PLATFORMS, 'mobile': MOBILE_PLATFORMS}
for app in applications.APPS_ALL.values():
    app.platforms = _platforms[app.platforms]
