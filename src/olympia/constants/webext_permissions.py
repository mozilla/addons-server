from collections import namedtuple

from django.utils.translation import ugettext_lazy as _lazy

Permission = namedtuple('Permission',
                        'name, description, long_description')


ALL_URLS_PERMISSION = Permission(
    u'all_urls',
    _lazy(u'Access your data for all websites'),
    '')

WEBEXT_PERMISSIONS = {
    u'<all_urls>': ALL_URLS_PERMISSION,
    u'http://*/*': ALL_URLS_PERMISSION,
    u'https://*/*': ALL_URLS_PERMISSION,
    u'*://*/*': ALL_URLS_PERMISSION,

    u'bookmarks': Permission(
        u'bookmarks',
        _lazy(u'Read and modify bookmarks'),
        ''),
    u'clipboardRead': Permission(
        u'clipboard',
        _lazy(u'Get data from the clipboard'),
        ''),
    u'clipboardWrite': Permission(
        u'clipboard',
        _lazy(u'Input data to the clipboard'),
        ''),
    u'downloads': Permission(
        u'downloads',
        _lazy(u"Download files and read and modify the browser's download "
              u"history"),
        ''),
    u'geolocation': Permission(
        u'history',
        _lazy(u'Access your location'),
        ''),
    u'history': Permission(
        u'history',
        _lazy(u'Access browsing history'),
        ''),
    u'nativeMessaging': Permission(
        u'nativeMessaging',
        _lazy(u'Exchange messages with programs other than Firefox'),
        ''),
    u'notifications': Permission(
        u'notifications',
        _lazy(u'Display notifications to you'),
        ''),
    u'sessions': Permission(
        u'sessions',
        _lazy(u'Access recently closed tabs'),
        ''),
    u'tabs': Permission(
        u'tabs',
        _lazy(u'Access browser tabs'),
        ''),
    u'topSites': Permission(
        u'topSites',
        _lazy(u'Access browsing history'),
        ''),
    u'webNavigation': Permission(
        u'webNavigation',
        _lazy(u'Access browser activity during navigation'),
        ''),
}
