from collections import namedtuple

from django.utils.translation import ugettext_lazy as _lazy

Permission = namedtuple('Permission',
                        'name, description, long_description')

WEBEXT_PERMISSIONS = {
    u'activeTab': Permission(
        u'activeTab',
        _lazy(u'Requests that the extension be granted permissions according '
              u'to the activeTab specification.'),
        _lazy(u'Requests that the extension be granted permissions according '
              u'to the activeTab specification.')
        ),
    u'alarms': Permission(
        u'alarms',
        _lazy(u'Gives the extension access to the chrome.alarms API.'),
        _lazy(u'Gives the extension access to the chrome.alarms API.')
        ),
    u'bookmarks': Permission(
        u'bookmarks',
        _lazy(u'Read and modify bookmarks.'),
        _lazy(u'Read and modify bookmarks.')
        ),
}
