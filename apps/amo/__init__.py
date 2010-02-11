"""
Miscellaneous helpers that make Django compatible with AMO.
"""
from django.utils.translation import ugettext as _


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
ADDON_ANY = -1
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
    ADDON_EXTENSION: _('Extension'),
    ADDON_THEME: _('Theme'),
    ADDON_DICT: _('Dictionary'),
    ADDON_SEARCH: _('Search Engine'),
    ADDON_PLUGIN: _('Plugin'),
    ADDON_PERSONA: _('Persona'),
}

# Plural
ADDON_TYPES = {
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

class THUNDERBIRD:
    id = 18
    short = 'thunderbird'
    pretty = _('Thunderbird')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_PERSONA]

class SEAMONKEY:
    id = 59
    short = 'seamonkey'
    pretty = _('SeaMonkey')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH,
             ADDON_PLUGIN]

class SUNBIRD:
    id = 52
    short = 'sunbird'
    pretty = _('Sunbird')
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT]

class MOBILE:
    id = 60
    short = 'mobile'
    pretty = _('Mobile')
    browser = True
    types = [ADDON_EXTENSION, ADDON_THEME, ADDON_DICT, ADDON_SEARCH]

_apps = (FIREFOX, THUNDERBIRD, SEAMONKEY, SUNBIRD, MOBILE)
APPS = dict((app.short, app) for app in _apps)
APP_IDS = dict((app.id, app) for app in _apps)
