"""
Miscellaneous helpers that make Django compatible with AMO.
"""
from licenses import license_text

import commonware.log
from tower import ugettext_lazy as _


# Every app should have its own logger.
log = commonware.log.getLogger('z.amo')


def cached_property(*args, **kw):
    # Handles invocation as a direct decorator or
    # with intermediate keyword arguments.
    if args:  # @cached_property
        return CachedProperty(args[0])
    else:     # @cached_property(name=..., writable=...)
        return lambda f: CachedProperty(f, **kw)


class CachedProperty(object):
    """A decorator that converts a function into a lazy property.  The
    function wrapped is called the first time to retrieve the result
    and than that calculated result is used the next time you access
    the value::

        class Foo(object):

            @cached_property
            def foo(self):
                # calculate something important here
                return 42

    Lifted from werkzeug.
    """

    def __init__(self, func, name=None, doc=None, writable=False):
        self.func = func
        self.writable = writable
        self.__name__ = name or func.__name__
        self.__doc__ = doc or func.__doc__

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        _missing = object()
        value = obj.__dict__.get(self.__name__, _missing)
        if value is _missing:
            value = self.func(obj)
            obj.__dict__[self.__name__] = value
        return value

    def __set__(self, obj, value):
        if not self.writable:
            raise TypeError('read only attribute')
        obj.__dict__[self.__name__] = value


# Add-on and File statuses.
STATUS_NULL = 0
STATUS_UNREVIEWED = 1
STATUS_PENDING = 2
STATUS_NOMINATED = 3
STATUS_PUBLIC = 4
STATUS_DISABLED = 5
STATUS_LISTED = 6
STATUS_BETA = 7

STATUS_CHOICES = {
    STATUS_NULL: 'Null',
    STATUS_UNREVIEWED: 'Not reviewed',
    STATUS_PENDING: 'Pending approval',
    STATUS_NOMINATED: 'Nominated to be public',
    STATUS_PUBLIC: 'Public',
    STATUS_DISABLED: 'Disabled',
    STATUS_LISTED: 'Listed',
    STATUS_BETA: 'Beta',
}

UNREVIEWED_STATUSES = (STATUS_UNREVIEWED, STATUS_PENDING, STATUS_NOMINATED)
VALID_STATUSES = (STATUS_UNREVIEWED, STATUS_PENDING, STATUS_NOMINATED,
                  STATUS_PUBLIC, STATUS_LISTED, STATUS_BETA)

# Add-on author roles.
AUTHOR_ROLE_NONE = 0
AUTHOR_ROLE_VIEWER = 1
AUTHOR_ROLE_DEV = 4
AUTHOR_ROLE_OWNER = 5
AUTHOR_ROLE_ADMIN = 6
AUTHOR_ROLE_ADMINOWNER = 7

AUTHOR_CHOICES = {
    AUTHOR_ROLE_NONE: 'None',
    AUTHOR_ROLE_VIEWER: 'Viewer',
    AUTHOR_ROLE_DEV: 'Developer',
    AUTHOR_ROLE_OWNER: 'Owner',
    AUTHOR_ROLE_ADMIN: 'Admin',
    AUTHOR_ROLE_ADMINOWNER: 'Admin & Owner',
}

# Addon types
ADDON_ANY = 0
ADDON_EXTENSION = 1
ADDON_THEME = 2
ADDON_DICT = 3
ADDON_SEARCH = 4
ADDON_LPAPP = 5
ADDON_LPADDON = 6
ADDON_PLUGIN = 7
ADDON_API = 8  # not actually a type but used to identify extensions + themes
ADDON_PERSONA = 9

# Singular
ADDON_TYPE = {
    ADDON_ANY: _(u'Any'),
    ADDON_EXTENSION: _(u'Extension'),
    ADDON_THEME: _(u'Theme'),
    ADDON_DICT: _(u'Dictionary'),
    ADDON_SEARCH: _(u'Search Engine'),
    ADDON_PLUGIN: _(u'Plugin'),
    ADDON_LPAPP: _(u'Language Pack (Application)'),
    ADDON_PERSONA: _(u'Persona'),
}

# Plural
ADDON_TYPES = {
    ADDON_ANY: _(u'Any'),
    ADDON_EXTENSION: _(u'Extensions'),
    ADDON_THEME: _(u'Themes'),
    ADDON_DICT: _(u'Dictionaries'),
    ADDON_SEARCH: _(u'Search Tools'),
    ADDON_PLUGIN: _(u'Plugins'),
    ADDON_LPAPP: _(u'Language Packs (Application)'),
    ADDON_PERSONA: _(u'Personas'),
}

# We use these slugs in browse page urls.
ADDON_SLUGS = {
    ADDON_EXTENSION: 'extensions',
    ADDON_THEME: 'themes',
    ADDON_DICT: 'language-tools',
    ADDON_LPAPP: 'language-tools',
    ADDON_PERSONA: 'personas',
    ADDON_SEARCH: 'search-tools',
}


# Applications
class FIREFOX:
    id = 1
    short = 'firefox'
    pretty = _(u'Firefox')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP, ADDON_PLUGIN, ADDON_PERSONA]
    guid = '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}'
    min_display_version = 3.0
    # These versions were relabeled and should not be displayed.
    exclude_versions = (3.1,)


class THUNDERBIRD:
    id = 18
    short = 'thunderbird'
    pretty = _(u'Thunderbird')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_LPAPP,
             ADDON_PERSONA]
    guid = '{3550f703-e582-4d05-9a08-453d09bdfdc6}'
    min_display_version = 1.0


class SEAMONKEY:
    id = 59
    short = 'seamonkey'
    pretty = _(u'SeaMonkey')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP, ADDON_PLUGIN]
    guid = '{92650c4d-4b8e-4d2a-b7eb-24ecf4f6b63a}'
    min_display_version = 1.0


class SUNBIRD:
    id = 52
    short = 'sunbird'
    pretty = _(u'Sunbird')
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_LPAPP]
    guid = '{718e30fb-e89b-41dd-9da7-e25a45638b28}'
    min_display_version = 0.2


class MOBILE:
    id = 60
    short = 'mobile'
    pretty = _(u'Mobile')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP]
    guid = '{a23983c0-fd0e-11dc-95ff-0800200c9a66}'
    min_display_version = 0.1


class MOZILLA:
    """Mozilla exists for completeness and historical purposes.

    Stats and other modules may reference this for history.
    This should NOT be added to APPS.
    """
    id = 2
    short = 'mz'
    pretty = _(u'Mozilla')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_LPAPP, ADDON_PLUGIN]
    guid = '{86c18b42-e466-45a9-ae7a-9b95ba6f5640}'

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


# Platforms
class PLATFORM_ANY:
    id = 0
    name = _('Any')
    shortname = 'any'
    # API name is not translated
    api_name = u'ALL'


class PLATFORM_ALL:
    id = 1
    name = _('All')
    shortname = 'all'
    api_name = u'ALL'


class PLATFORM_LINUX:
    id = 2
    name = _('Linux')
    shortname = 'linux'
    api_name = u'Linux'


class PLATFORM_MAC:
    id = 3
    name = _('Mac OS X')
    shortname = 'mac'
    api_name = u'Darwin'


class PLATFORM_BSD:
    id = 4
    name = _('BSD')
    shortname = 'bsd'
    api_name = u'BSD_OS'


class PLATFORM_WIN:
    id = 5
    name = _('Windows')
    shortname = 'windows'
    api_name = u'WINNT'


class PLATFORM_SUN:
    id = 6
    name = _('Solaris')
    shortname = 'solaris'
    api_name = 'SunOS'

# Order matters
PLATFORMS = {PLATFORM_ANY.id: PLATFORM_ANY, PLATFORM_ALL.id: PLATFORM_ALL,
             PLATFORM_LINUX.id: PLATFORM_LINUX, PLATFORM_MAC.id: PLATFORM_MAC,
             PLATFORM_BSD.id: PLATFORM_BSD, PLATFORM_WIN.id: PLATFORM_WIN,
             PLATFORM_SUN.id: PLATFORM_SUN}

PLATFORM_DICT = {
    'all': PLATFORM_ALL,
    'linux': PLATFORM_LINUX,
    'mac': PLATFORM_MAC,
    'macosx': PLATFORM_MAC,
    'darwin': PLATFORM_MAC,
    'bsd': PLATFORM_BSD,
    'bsd_os': PLATFORM_BSD,
    'win': PLATFORM_WIN,
    'winnt': PLATFORM_WIN,
    'windows': PLATFORM_WIN,
    'sun': PLATFORM_SUN,
    'sunos': PLATFORM_SUN,
    'solaris': PLATFORM_SUN,
}


# Built-in Licenses
class _LicenseBase(object):
    """Base class for built-in licenses."""
    shortname = None
    icons = None     # CSS classes. See zamboni.css for a list.
    linktext = None  # Link text distinct from full license name.

    @classmethod
    def text(cls):
        return cls.shortname and license_text(cls.shortname) or None


class LICENSE_CUSTOM(_LicenseBase):
    """
    Not an actual license, but used as a placeholder for author-defined
    licenses
    """
    id = -1
    name = _(u'Custom License')
    url = None
    shortname = None


class LICENSE_MPL(_LicenseBase):
    id = 0
    name = _(u'Mozilla Public License, version 1.1')
    url = 'http://www.mozilla.org/MPL/MPL-1.1.html'
    shortname = 'mpl'


class LICENSE_GPL2(_LicenseBase):
    id = 1
    name = _(u'GNU General Public License, version 2.0')
    url = 'http://www.gnu.org/licenses/gpl-2.0.html'
    shortname = 'gpl2'


class LICENSE_GPL3(_LicenseBase):
    id = 2
    name = _(u'GNU General Public License, version 3.0')
    url = 'http://www.gnu.org/licenses/gpl-3.0.html'
    shortname = 'gpl3'


class LICENSE_LGPL21(_LicenseBase):
    id = 3
    name = 'GNU Lesser General Public License, version 2.1'
    url = 'http://www.gnu.org/licenses/lgpl-2.1.html'
    shortname = 'lgpl21'


class LICENSE_LGPL3(_LicenseBase):
    id = 4
    name = _(u'GNU Lesser General Public License, version 3.0')
    url = 'http://www.gnu.org/licenses/lgpl-3.0.html'
    shortname = 'lgpl3'


class LICENSE_MIT(_LicenseBase):
    id = 5
    name = _(u'MIT/X11 License')
    url = 'http://www.opensource.org/licenses/mit-license.php'
    shortname = 'mit'


class LICENSE_BSD(_LicenseBase):
    id = 6
    name = _(u'BSD License')
    url = 'http://www.opensource.org/licenses/bsd-license.php'
    shortname = 'bsd'


class LICENSE_COPYRIGHT(_LicenseBase):
    id = 7
    name = _(u'All Rights Reserved')
    url = None
    shortname = None
    icons = ('copyr',)


class LICENSE_CC_BY_NC_SA(_LicenseBase):
    id = 8
    name = _(u'Creative Commons Attribution-Noncommercial-Share Alike 3.0')
    linktext = _(u'Some rights reserved')
    url = 'http://creativecommons.org/licenses/by-nc-sa/3.0/'
    shortname = None
    icons = ('cc-attrib', 'cc-noncom', 'cc-share')

LICENSES = (LICENSE_CUSTOM, LICENSE_COPYRIGHT, LICENSE_MPL, LICENSE_GPL2,
            LICENSE_GPL3, LICENSE_LGPL21, LICENSE_LGPL3, LICENSE_MIT,
            LICENSE_BSD, LICENSE_CC_BY_NC_SA)
LICENSE_IDS = dict((license.id, license) for license in LICENSES)


# Contributions
CONTRIB_NONE = 0
CONTRIB_PASSIVE = 1
CONTRIB_AFTER = 2
CONTRIB_ROADBLOCK = 3

CONTRIB_CHOICES = {
    CONTRIB_NONE: 'None',
    CONTRIB_PASSIVE: 'Passive; user shown message next to download button',
    CONTRIB_AFTER: 'User shown splash screen after download',
    CONTRIB_ROADBLOCK: 'Roadblock; User shown splash screen before download',
}

# Personas
PERSONAS_ADDON_ID = 10900 # Add-on ID of the Personas Plus Add-on
PERSONAS_FIREFOX_MIN = '3.6' # First Firefox version to support Personas
PERSONAS_THUNDERBIRD_MIN = '3.1' # Ditto for Thunderbird

# Collections.
COLLECTION_NORMAL = 0
COLLECTION_SYNCHRONIZED = 1
COLLECTION_FEATURED = 2
COLLECTION_RECOMMENDED = 3

COLLECTION_CHOICES = {
    COLLECTION_NORMAL: 'Normal',
    COLLECTION_SYNCHRONIZED: 'Synchronized',
    COLLECTION_FEATURED: 'Featured',
    COLLECTION_RECOMMENDED: 'Generated Recommendations',
}

COLLECTION_ROLE_PUBLISHER = 0
COLLECTION_ROLE_ADMIN = 1

COLLECTION_AUTHOR_CHOICES = {
    COLLECTION_ROLE_PUBLISHER: 'Publisher',
    COLLECTION_ROLE_ADMIN: 'Admin',
}
