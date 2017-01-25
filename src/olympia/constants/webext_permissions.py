from inspect import isclass

from django.utils.translation import ugettext_lazy as _lazy


# Known Webextension permssions.
class _WebextPermissionBase(object):
    """Base class for known permissions."""
    pass


class WEBEXT_UNKNOWN(_WebextPermissionBase):
    id = 0
    name = ''
    pretty_name = _lazy(u'Unsupported permission.')
    description = ''


class WEBEXT_ACTIVETAB(_WebextPermissionBase):
    id = 1
    name = u'activeTab'
    pretty_name = _lazy(u'Active Tab')
    description = _lazy(u'Requests that the extension be granted permissions'
                        u'according to the activeTab specification.')


class WEBEXT_ALARMS(_WebextPermissionBase):
    id = 2
    name = u'alarms'
    pretty_name = _lazy(u'Alarms')
    description = _lazy(u'Gives the extension access to the chrome.alarms'
                        u'API.')


class WEBEXT_BOOKMARKS(_WebextPermissionBase):
    id = 3
    name = u'bookmarks'
    pretty_name = _lazy(u'Bookmarks')
    description = _lazy(u'Read and modify bookmarks.')


WEBEXT_PERMISSIONS = [
    x for x in vars().values()
    if (isclass(x) and issubclass(x, _WebextPermissionBase) and
        x != _WebextPermissionBase)]
WEBEXT_PERMISSIONS_DICT = {
    l.name: l for l in WEBEXT_PERMISSIONS if l != WEBEXT_UNKNOWN}
WEBEXT_PERMISSIONS_IDS = {l.id: l for l in WEBEXT_PERMISSIONS}
