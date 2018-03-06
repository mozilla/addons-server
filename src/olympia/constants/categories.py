from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

from olympia.constants.applications import (
    ANDROID, FIREFOX, SEAMONKEY, THUNDERBIRD)
from olympia.constants.base import (
    ADDON_DICT, ADDON_EXTENSION, ADDON_LPAPP, ADDON_PERSONA, ADDON_SEARCH,
    ADDON_SLUGS, ADDON_STATICTHEME, ADDON_THEME)


class StaticCategory(object):
    """Helper to populate `CATEGORIES` and provide some helpers.

    Note that any instance is immutable to avoid changing values
    on the globally unique instances during test runs which can lead
    to hard to debug sporadic test-failures.
    """

    def __init__(self, id=None, app=None, type=None, misc=False,
                 name=None, slug=None, weight=0, description=None):
        # Avoid triggering our own __setattr__ implementation
        # to keep immutability intact but set initial values.
        object.__setattr__(self, 'id', id)
        object.__setattr__(self, 'application', app)
        object.__setattr__(self, 'misc', misc)
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'slug', slug)
        object.__setattr__(self, 'type', type)
        object.__setattr__(self, 'weight', weight)
        object.__setattr__(self, 'description', description)

    def __unicode__(self):
        return unicode(self.name)

    def __repr__(self):
        return u'<%s: %s (%s)>' % (
            self.__class__.__name__, self.__unicode__(), self.application)

    def get_url_path(self):
        try:
            type = ADDON_SLUGS[self.type]
        except KeyError:
            type = ADDON_SLUGS[ADDON_EXTENSION]
        return reverse('browse.%s' % type, args=[self.slug])

    def _immutable(self, *args):
        raise TypeError('%r instances are immutable' %
                        self.__class__.__name__)

    __setattr__ = __delattr__ = _immutable
    del _immutable


CATEGORIES = {
    FIREFOX.id: {
        ADDON_EXTENSION: {
            'alerts-updates': StaticCategory(
                id=72, name=_(u'Alerts & Updates')),
            'appearance': StaticCategory(id=14, name=_(u'Appearance')),
            'bookmarks': StaticCategory(id=22, name=_(u'Bookmarks')),
            'download-management': StaticCategory(
                id=5, name=_(u'Download Management')),
            'feeds-news-blogging': StaticCategory(
                id=1, name=_(u'Feeds, News & Blogging')),
            'games-entertainment': StaticCategory(
                id=142, name=_(u'Games & Entertainment')),
            'language-support': StaticCategory(
                id=37, name=_(u'Language Support')),
            'photos-music-videos': StaticCategory(
                id=38, name=_(u'Photos, Music & Videos')),
            'privacy-security': StaticCategory(
                id=12, name=_(u'Privacy & Security')),
            'search-tools': StaticCategory(id=13, name=_(u'Search Tools')),
            'shopping': StaticCategory(id=141, name=_(u'Shopping')),
            'social-communication': StaticCategory(
                id=71, name=_(u'Social & Communication')),
            'tabs': StaticCategory(id=93, name=_(u'Tabs')),
            'web-development': StaticCategory(
                id=4, name=_(u'Web Development')),
            'other': StaticCategory(id=73, name=_(u'Other'), weight=333)
        },
        ADDON_THEME: {
            'animals': StaticCategory(id=30, name=_(u'Animals')),
            'compact': StaticCategory(id=32, name=_(u'Compact')),
            'large': StaticCategory(id=67, name=_(u'Large')),
            'miscellaneous': StaticCategory(id=21, name=_(u'Miscellaneous')),
            'modern': StaticCategory(id=62, name=_(u'Modern')),
            'nature': StaticCategory(id=29, name=_(u'Nature')),
            'os-integration': StaticCategory(id=61, name=_(u'OS Integration')),
            'retro': StaticCategory(id=31, name=_(u'Retro')),
            'sports': StaticCategory(id=26, name=_(u'Sports'))
        },
        ADDON_STATICTHEME: {
            'abstract': StaticCategory(id=300, name=_(u'Abstract')),
            'causes': StaticCategory(id=320, name=_(u'Causes')),
            'fashion': StaticCategory(id=324, name=_(u'Fashion')),
            'film-and-tv': StaticCategory(id=326, name=_(u'Film and TV')),
            'firefox': StaticCategory(id=308, name=_(u'Firefox')),
            'foxkeh': StaticCategory(id=310, name=_(u'Foxkeh')),
            'holiday': StaticCategory(id=328, name=_(u'Holiday')),
            'music': StaticCategory(id=322, name=_(u'Music')),
            'nature': StaticCategory(id=302, name=_(u'Nature')),
            'other': StaticCategory(id=314, name=_(u'Other'), weight=333),
            'scenery': StaticCategory(id=306, name=_(u'Scenery')),
            'seasonal': StaticCategory(id=312, name=_(u'Seasonal')),
            'solid': StaticCategory(id=318, name=_(u'Solid')),
            'sports': StaticCategory(id=304, name=_(u'Sports')),
            'websites': StaticCategory(id=316, name=_(u'Websites'))
        },
        ADDON_DICT: {
            'general': StaticCategory(id=95, name=_(u'General'))
        },
        ADDON_SEARCH: {
            'bookmarks': StaticCategory(id=79, name=_(u'Bookmarks')),
            'business': StaticCategory(id=80, name=_(u'Business')),
            'dictionaries-encyclopedias': StaticCategory(
                id=81, name=_(u'Dictionaries & Encyclopedias')),
            'general': StaticCategory(id=82, name=_(u'General')),
            'kids': StaticCategory(id=83, name=_(u'Kids')),
            'multiple-search': StaticCategory(
                id=84, name=_(u'Multiple Search')),
            'music': StaticCategory(id=85, name=_(u'Music')),
            'news-blogs': StaticCategory(id=86, name=_(u'News & Blogs')),
            'photos-images': StaticCategory(id=87, name=_(u'Photos & Images')),
            'shopping-e-commerce': StaticCategory(
                id=88, name=_(u'Shopping & E-Commerce')),
            'social-people': StaticCategory(id=89, name=_(u'Social & People')),
            'sports': StaticCategory(id=90, name=_(u'Sports')),
            'travel': StaticCategory(id=91, name=_(u'Travel')),
            'video': StaticCategory(id=78, name=_(u'Video'))
        },
        ADDON_LPAPP: {
            'general': StaticCategory(id=98, name=_(u'General'))
        },
        ADDON_PERSONA: {
            'abstract': StaticCategory(id=100, name=_(u'Abstract')),
            'causes': StaticCategory(id=120, name=_(u'Causes')),
            'fashion': StaticCategory(id=124, name=_(u'Fashion')),
            'film-and-tv': StaticCategory(id=126, name=_(u'Film and TV')),
            'firefox': StaticCategory(id=108, name=_(u'Firefox')),
            'foxkeh': StaticCategory(id=110, name=_(u'Foxkeh')),
            'holiday': StaticCategory(id=128, name=_(u'Holiday')),
            'music': StaticCategory(id=122, name=_(u'Music')),
            'nature': StaticCategory(id=102, name=_(u'Nature')),
            'other': StaticCategory(id=114, name=_(u'Other')),
            'scenery': StaticCategory(id=106, name=_(u'Scenery')),
            'seasonal': StaticCategory(id=112, name=_(u'Seasonal')),
            'solid': StaticCategory(id=118, name=_(u'Solid')),
            'sports': StaticCategory(id=104, name=_(u'Sports')),
            'websites': StaticCategory(id=116, name=_(u'Websites'))
        }
    },
    ANDROID.id: {
        ADDON_EXTENSION: {
            'device-features-location': StaticCategory(
                id=145, name=_(u'Device Features & Location')),
            'experimental': StaticCategory(id=151, name=_(u'Experimental')),
            'feeds-news-blogging': StaticCategory(
                id=147, name=_(u'Feeds, News, & Blogging')),
            'performance': StaticCategory(id=144, name=_(u'Performance')),
            'photos-media': StaticCategory(id=143, name=_(u'Photos & Media')),
            'security-privacy': StaticCategory(
                id=149, name=_(u'Security & Privacy')),
            'shopping': StaticCategory(id=150, name=_(u'Shopping')),
            'social-networking': StaticCategory(
                id=148, name=_(u'Social Networking')),
            'sports-games': StaticCategory(id=146, name=_(u'Sports & Games')),
            'user-interface': StaticCategory(
                id=152, name=_(u'User Interface')),
            'other': StaticCategory(id=153, name=_(u'Other'), weight=333)
        }
    },
    THUNDERBIRD.id: {
        ADDON_EXTENSION: {
            'appearance': StaticCategory(
                id=208, name=_(u'Appearance and Customization')),
            'calendar': StaticCategory(
                id=204, name=_(u'Calendar and Date/Time')),
            'chat': StaticCategory(id=210, name=_(u'Chat and IM')),
            'composition': StaticCategory(
                id=202, name=_(u'Message Composition')),
            'contacts': StaticCategory(id=23, name=_(u'Contacts')),
            'folders-and-filters': StaticCategory(
                id=200, name=_(u'Folders and Filters')),
            'importexport': StaticCategory(id=206, name=_(u'Import/Export')),
            'language-support': StaticCategory(
                id=69, name=_(u'Language Support')),
            'message-and-news-reading': StaticCategory(
                id=58, name=_(u'Message and News Reading')),
            'miscellaneous': StaticCategory(id=50, name=_(u'Miscellaneous')),
            'privacy-and-security': StaticCategory(
                id=66, name=_(u'Privacy and Security')),
            'tags': StaticCategory(id=212, name=_(u'Tags'))
        },
        ADDON_THEME: {
            'compact': StaticCategory(id=64, name=_(u'Compact')),
            'miscellaneous': StaticCategory(id=60, name=_(u'Miscellaneous')),
            'modern': StaticCategory(id=63, name=_(u'Modern')),
            'nature': StaticCategory(id=65, name=_(u'Nature'))
        },
        ADDON_DICT: {
            'general': StaticCategory(id=97, name=_(u'General'))
        },
        ADDON_LPAPP: {
            'general': StaticCategory(id=99, name=_(u'General'))
        }
    },
    SEAMONKEY.id: {
        ADDON_EXTENSION: {
            'bookmarks': StaticCategory(id=51, name=_(u'Bookmarks')),
            'downloading-and-file-management': StaticCategory(
                id=42, name=_(u'Downloading and File Management')),
            'interface-customizations': StaticCategory(
                id=48, name=_(u'Interface Customizations')),
            'language-support-and-translation': StaticCategory(
                id=55, name=_(u'Language Support and Translation')),
            'miscellaneous': StaticCategory(
                id=49, name=_(u'Miscellaneous')),
            'photos-and-media': StaticCategory(
                id=56, name=_(u'Photos and Media')),
            'privacy-and-security': StaticCategory(
                id=46, name=_(u'Privacy and Security')),
            'rss-news-and-blogging': StaticCategory(
                id=39, name=_(u'RSS, News and Blogging')),
            'search-tools': StaticCategory(id=47, name=_(u'Search Tools')),
            'site-specific': StaticCategory(id=52, name=_(u'Site-specific')),
            'web-and-developer-tools': StaticCategory(
                id=41, name=_(u'Web and Developer Tools'))
        },
        ADDON_THEME: {
            'miscellaneous': StaticCategory(id=59, name=_(u'Miscellaneous'))
        },
        ADDON_DICT: {
            'general': StaticCategory(id=96, name=_(u'General'))
        },
        ADDON_LPAPP: {
            'general': StaticCategory(id=130, name=_(u'General'))
        }
    },
}

CATEGORIES_BY_ID = {}

for app in CATEGORIES:
    for type_ in CATEGORIES[app]:
        for slug in CATEGORIES[app][type_]:
            cat = CATEGORIES[app][type_][slug]

            # Flatten some values and set them, avoiding immutability
            # of `StaticCategory` by calling `object.__setattr__` directly.
            if slug in ('miscellaneous', 'other'):
                object.__setattr__(cat, 'misc', True)
            object.__setattr__(cat, 'slug', slug)
            object.__setattr__(cat, 'application', app)
            object.__setattr__(cat, 'type', type_)
            CATEGORIES_BY_ID[cat.id] = cat
