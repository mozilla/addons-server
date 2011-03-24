"""
Miscellaneous helpers that make Django compatible with AMO.
"""
import re
import threading

import commonware.log
from django.utils.datastructures import SortedDict
from tower import ugettext_lazy as _

from product_details import firefox_versions, thunderbird_versions
from versions.compare import version_int
from licenses import license_text
from .log import LOG, LOG_BY_ID, LOG_EDITORS, LOG_KEEP, LOG_REVIEW_QUEUE, log

logger_log = commonware.log.getLogger('z.amo')

_locals = threading.local()
_locals.user = None


def get_user():
    return _locals.user


def set_user(user):
    _locals.user = user


def cached_property(*args, **kw):
    # Handles invocation as a direct decorator or
    # with intermediate keyword arguments.
    if args:  # @cached_property
        return CachedProperty(args[0])
    else:     # @cached_property(name=..., writable=...)
        return lambda f: CachedProperty(f, **kw)


class CachedProperty(object):
    """
    A decorator that converts a function into a lazy property.  The
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
STATUS_LITE = 8
STATUS_LITE_AND_NOMINATED = 9
STATUS_PURGATORY = 10  # A temporary home; bug 614686

STATUS_CHOICES = {
    STATUS_NULL: _(u'Incomplete'),
    STATUS_UNREVIEWED: _(u'Awaiting Preliminary Review'),
    STATUS_PENDING: _(u'Pending approval'),
    STATUS_NOMINATED: _(u'Awaiting Full Review'),
    STATUS_PUBLIC: _(u'Fully Reviewed'),
    STATUS_DISABLED: _(u'Disabled by Mozilla'),
    STATUS_LISTED: _(u'Listed'),
    STATUS_BETA: _(u'Beta'),
    STATUS_LITE: _(u'Preliminarily Reviewed'),
    STATUS_LITE_AND_NOMINATED:
        _(u'Preliminarily Reviewed and Awaiting Full Review'),
    STATUS_PURGATORY:
        _(u'Pending a review choice'),
}

UNREVIEWED_STATUSES = (STATUS_UNREVIEWED, STATUS_PENDING, STATUS_NOMINATED,
                       STATUS_PURGATORY)
VALID_STATUSES = (STATUS_UNREVIEWED, STATUS_PENDING, STATUS_NOMINATED,
                  STATUS_PUBLIC, STATUS_LISTED, STATUS_BETA, STATUS_LITE,
                  STATUS_LITE_AND_NOMINATED, STATUS_PURGATORY)
# We don't show addons/versions with UNREVIEWED_STATUS in public.
LISTED_STATUSES = tuple(st for st in VALID_STATUSES
                        if st not in (STATUS_PENDING,))

# An add-on in one of these statuses is awaiting a review.
STATUS_UNDER_REVIEW = (STATUS_UNREVIEWED, STATUS_NOMINATED,
                       STATUS_LITE_AND_NOMINATED)

LITE_STATUSES = (STATUS_LITE, STATUS_LITE_AND_NOMINATED)

MIRROR_STATUSES = (STATUS_PUBLIC, STATUS_BETA,
                   STATUS_LITE, STATUS_LITE_AND_NOMINATED)

# Types of administrative review queues for an add-on:
ADMIN_REVIEW_FULL = 1
ADMIN_REVIEW_PRELIM = 2

ADMIN_REVIEW_TYPES = {
    ADMIN_REVIEW_FULL: _(u'Full'),
    ADMIN_REVIEW_PRELIM: _(u'Preliminary'),
}

# Add-on author roles.
AUTHOR_ROLE_VIEWER = 1
AUTHOR_ROLE_DEV = 4
AUTHOR_ROLE_OWNER = 5

AUTHOR_CHOICES = (
    (AUTHOR_ROLE_OWNER, _(u'Owner')),
    (AUTHOR_ROLE_DEV, _(u'Developer')),
    (AUTHOR_ROLE_VIEWER, _(u'Viewer')),
)

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

# Icons
ADDON_ICONS = {
    ADDON_ANY: 'default-addon.png',
    ADDON_THEME: 'default-theme.png',
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

# These are used in the update API.
ADDON_SLUGS_UPDATE = {
    ADDON_EXTENSION: 'extension',
    ADDON_THEME: 'theme',
    ADDON_DICT: 'extension',
    ADDON_SEARCH: 'search',
    ADDON_LPAPP: 'item',
    ADDON_LPADDON: 'extension',
    ADDON_PERSONA: 'persona',
    ADDON_PLUGIN: 'plugin',
}

# Edit addon information
MAX_TAGS = 20
MIN_TAG_LENGTH = 2
MAX_CATEGORIES = 2

# Icon upload sizes
ADDON_ICON_SIZES = [32, 48, 64]

# Preview upload sizes [thumb, full]
ADDON_PREVIEW_SIZES = [(200, 150), (700, 525)]

# These types don't maintain app compatibility in the db.  Instead, we look at
# APP.types and APP_TYPE_SUPPORT to figure out where they are compatible.
NO_COMPAT = (ADDON_SEARCH, ADDON_PERSONA)
HAS_COMPAT = dict((t, t not in NO_COMPAT) for t in ADDON_TYPES)


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
    latest_version = firefox_versions['LATEST_FIREFOX_VERSION']
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
    latest_version = thunderbird_versions['LATEST_THUNDERBIRD_VERSION']
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
    on_form = True

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
    shortname = 'other'


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
    on_form = False


class LICENSE_CC_BY_NC_SA(_LicenseBase):
    id = 8
    name = _(u'Creative Commons Attribution-Noncommercial-Share Alike 3.0')
    linktext = _(u'Some rights reserved')
    url = 'http://creativecommons.org/licenses/by-nc-sa/3.0/'
    shortname = None
    icons = ('cc-attrib', 'cc-noncom', 'cc-share')
    on_form = False

LICENSES = (LICENSE_CUSTOM, LICENSE_COPYRIGHT, LICENSE_MPL, LICENSE_GPL2,
            LICENSE_GPL3, LICENSE_LGPL21, LICENSE_LGPL3, LICENSE_MIT,
            LICENSE_BSD, LICENSE_CC_BY_NC_SA)
LICENSE_IDS = dict((license.id, license) for license in LICENSES)


# Contributions
CONTRIB_NONE = 0
CONTRIB_PASSIVE = 1
CONTRIB_AFTER = 2
CONTRIB_ROADBLOCK = 3

CONTRIB_CHOICES = (
    (CONTRIB_PASSIVE,
     _(u"Only ask on this add-on's page and developer profile")),
    (CONTRIB_AFTER, _(u"Ask after users start downloading this add-on")),
    (CONTRIB_ROADBLOCK, _(u"Ask before users can download this add-on")),
)

# Personas
PERSONAS_ADDON_ID = 10900  # Add-on ID of the Personas Plus Add-on
PERSONAS_FIREFOX_MIN = '3.6'  # First Firefox version to support Personas
PERSONAS_THUNDERBIRD_MIN = '3.1'  # Ditto for Thunderbird

# Collections.
COLLECTION_NORMAL = 0
COLLECTION_SYNCHRONIZED = 1
COLLECTION_FEATURED = 2
COLLECTION_RECOMMENDED = 3
COLLECTION_FAVORITES = 4
COLLECTION_MOBILE = 5
COLLECTION_ANONYMOUS = 6

COLLECTIONS_NO_CONTRIB = (COLLECTION_SYNCHRONIZED, COLLECTION_FAVORITES)

COLLECTION_SPECIAL_SLUGS = {
    COLLECTION_MOBILE: 'mobile',
    COLLECTION_FAVORITES: 'favorites',
}

COLLECTION_CHOICES = {
    COLLECTION_NORMAL: 'Normal',
    COLLECTION_SYNCHRONIZED: 'Synchronized',
    COLLECTION_FEATURED: 'Featured',
    COLLECTION_RECOMMENDED: 'Generated Recommendations',
    COLLECTION_FAVORITES: 'Favorites',
    COLLECTION_MOBILE: 'Mobile',
    COLLECTION_ANONYMOUS: 'Anonymous',
}

COLLECTION_ROLE_PUBLISHER = 0
COLLECTION_ROLE_ADMIN = 1

COLLECTION_AUTHOR_CHOICES = {
    COLLECTION_ROLE_PUBLISHER: 'Publisher',
    COLLECTION_ROLE_ADMIN: 'Admin',
}

# Contributions.
FOUNDATION_ORG = 1  # The charities.id of the Mozilla Foundation.

VERSION_BETA = re.compile('(a|alpha|b|beta|pre|rc)\d*$')
VERSION_SEARCH = re.compile('\.(\d+)$')
