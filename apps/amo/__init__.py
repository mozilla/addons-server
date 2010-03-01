"""
Miscellaneous helpers that make Django compatible with AMO.
"""
from l10n import ugettext as _


class cached_property(object):
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

    def __init__(self, func, name=None, doc=None, writeable=False):
        self.func = func
        self.writeable = writeable
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
        if not self.writeable:
            raise TypeError('read only attribute')
        obj.__dict__[self.__name__] = value


# Add-on and File statuses.
STATUS_NULL = 0
STATUS_SANDBOX = 1
STATUS_PENDING = 2
STATUS_NOMINATED = 3
STATUS_PUBLIC = 4
STATUS_DISABLED = 5
STATUS_LISTED = 6
STATUS_BETA = 7

STATUS_CHOICES = {
    STATUS_NULL: 'Null',
    STATUS_SANDBOX: 'In the sandbox',
    STATUS_PENDING: 'Pending approval',
    STATUS_NOMINATED: 'Nominated to be public',
    STATUS_PUBLIC: 'Public',
    STATUS_DISABLED: 'Disabled',
    STATUS_LISTED: 'Listed',
    STATUS_BETA: 'Beta',
}

EXPERIMENTAL_STATUSES = (STATUS_SANDBOX, STATUS_PENDING, STATUS_NOMINATED)
VALID_STATUSES = (STATUS_SANDBOX, STATUS_PENDING, STATUS_NOMINATED,
                  STATUS_PUBLIC, STATUS_LISTED)

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

# Collection author roles.
COLLECTION_ROLE_PUBLISHER = 0
COLLECTION_ROLE_ADMIN = 1

COLLECTION_AUTHOR_CHOICES = {
    COLLECTION_ROLE_PUBLISHER: 'Publisher',
    COLLECTION_ROLE_ADMIN: 'Admin',
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
ADDON_API = 8 # not actually a type but used to identify extensions + themes
ADDON_PERSONA = 9

# Singular
ADDON_TYPE = {
    ADDON_ANY: _('Any'),
    ADDON_EXTENSION: _('Extension'),
    ADDON_THEME: _('Theme'),
    ADDON_DICT: _('Dictionary'),
    ADDON_SEARCH: _('Search Engine'),
    ADDON_PLUGIN: _('Plugin'),
    ADDON_LPAPP: _('Language Pack (Application)'),
    ADDON_PERSONA: _('Persona'),
}

# Plural
ADDON_TYPES = {
    ADDON_ANY: _('Any'),
    ADDON_EXTENSION: _('Extensions'),
    ADDON_THEME: _('Themes'),
    ADDON_DICT: _('Dictionaries & Language Packs'),
    ADDON_SEARCH: _('Search Tools'),
    ADDON_PLUGIN: _('Plugins'),
    ADDON_PERSONA: _('Personas'),
}


# Applications
class FIREFOX:
    id = 1
    short = 'firefox'
    pretty = _('Firefox')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_PLUGIN, ADDON_PERSONA]
    guid = '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}'


class THUNDERBIRD:
    id = 18
    short = 'thunderbird'
    pretty = _('Thunderbird')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_PERSONA]
    guid = '{3550f703-e582-4d05-9a08-453d09bdfdc6}'

class SEAMONKEY:
    id = 59
    short = 'seamonkey'
    pretty = _('SeaMonkey')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_PLUGIN]
    guid = '{92650c4d-4b8e-4d2a-b7eb-24ecf4f6b63a}'


class SUNBIRD:
    id = 52
    short = 'sunbird'
    pretty = _('Sunbird')
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT]
    guid = '{718e30fb-e89b-41dd-9da7-e25a45638b28}'


class MOBILE:
    id = 60
    short = 'mobile'
    pretty = _('Mobile')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH]
    guid = '{a23983c0-fd0e-11dc-95ff-0800200c9a66}'

class MOZILLA:
    """Mozilla exists for completeness and historical purposes.

    Stats and other modules may reference this for history.
    This should NOT be added to APPS.
    """
    id = 2
    short = 'mz'
    pretty = _('Mozilla')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_PLUGIN]
    guid = '{86c18b42-e466-45a9-ae7a-9b95ba6f5640}'

APP_USAGE = _apps = (FIREFOX, THUNDERBIRD, MOBILE, SEAMONKEY, SUNBIRD)
APPS = dict((app.short, app) for app in _apps)
APP_IDS = dict((app.id, app) for app in _apps)
APP_GUIDS = dict((app.guid, app) for app in _apps)
APPS_RETIRED = dict([(MOZILLA.short, MOZILLA)])

# Platforms
PLATFORM_ANY = 0
PLATFORM_ALL = 1
PLATFORM_LINUX = 2
PLATFORM_MAC = 3
PLATFORM_BSD = 4
PLATFORM_WIN = 5
PLATFORM_SUN = 6

PLATFORMS = {
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
    PLATFORM_ANY: _('Any'),
    PLATFORM_ALL: _('All'),
    PLATFORM_LINUX: _('Linux'),
    PLATFORM_MAC: _('Mac OS X'),
    PLATFORM_BSD: _('BSD'),
    PLATFORM_WIN: _('Windows'),
    PLATFORM_SUN: _('Solaris'),
}

# Built-in Licenses
# TODO: actual license texts for all but custom license
class LICENSE_CUSTOM:
    """
    Not an actual license, but used as a placeholder for author-defined
    licenses
    """
    id = -1
    name = _('Custom License')
    url = None
    text = None

class LICENSE_MPL:
    id = 0
    name = _('Mozilla Public License, version 1.1')
    url = 'http://www.mozilla.org/MPL/MPL-1.1.html'
    text = 'MPL License Text'

class LICENSE_GPL2:
    id = 1
    name = _('GNU General Public License, version 2.0')
    url = 'http://www.gnu.org/licenses/gpl-2.0.html'
    text = 'GPL2 license text'

class LICENSE_GPL3:
    id = 2
    name = _('GNU General Public License, version 3.0')
    url = 'http://www.gnu.org/licenses/gpl-3.0.html'
    text = 'GPL3 license text'

class LICENSE_LGPL21:
    id = 3
    name = 'GNU Lesser General Public License, version 2.1'
    url = 'http://www.gnu.org/licenses/lgpl-2.1.html'
    text = 'LGPL21 license text'

class LICENSE_LGPL3:
    id = 4
    name = _('GNU Lesser General Public License, version 3.0')
    url = 'http://www.gnu.org/licenses/lgpl-3.0.html'
    text = 'LGPL3 license text'

class LICENSE_MIT:
    id = 5
    name = _('MIT/X11 License')
    url = 'http://www.opensource.org/licenses/mit-license.php'
    text = 'MIT license text'

class LICENSE_BSD:
    id = 6
    name = _('BSD License')
    url = 'http://www.opensource.org/licenses/bsd-license.php'
    text = 'BSD license text'

LICENSES = (LICENSE_CUSTOM, LICENSE_MPL, LICENSE_GPL2, LICENSE_GPL3,
            LICENSE_LGPL21, LICENSE_LGPL3, LICENSE_MIT, LICENSE_BSD)
LICENSE_IDS = dict((license.id, license) for license in LICENSES)
