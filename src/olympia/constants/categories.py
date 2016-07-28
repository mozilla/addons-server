import collections

from django.utils.datastructures import SortedDict
from django.utils.translation import ugettext_lazy as _

from olympia.constants.applications import (
    ANDROID, FIREFOX, MOBILE, SEAMONKEY, THUNDERBIRD)
from olympia.constants.base import (
    ADDON_DICT, ADDON_EXTENSION, ADDON_LPAPP, ADDON_PERSONA, ADDON_SEARCH,
    ADDON_THEME)


StaticCategory = collections.namedtuple('StaticCategory', ['id', 'name'])

# How to fetch existing translations ?
# Maybe a script to be run in prod, or an API to fetch existing
# categories in the right language, like we had on Marketplace ?

categories = {
    FIREFOX.id: SortedDict({
        ADDON_EXTENSION: SortedDict({
            'alerts-updates': StaticCategory(
                id=72, name=_('Alerts & Updates')),
            'appearance': StaticCategory(id=14, name=_('Appearance')),
            'bookmarks': StaticCategory(id=22, name=_('Bookmarks')),
            'download-management': StaticCategory(
                id=5, name=_('Download Management')),
            'feeds-news-blogging': StaticCategory(
                id=1, name=_('Feeds, News & Blogging')),
            'games-entertainment': StaticCategory(
                id=142, name=_('Games & Entertainment')),
            'language-support': StaticCategory(
                id=37, name=_('Language Support')),
            'photos-music-videos': StaticCategory(
                id=38, name=_('Photos, Music & Videos')),
            'privacy-security': StaticCategory(
                id=12, name=_('Privacy & Security')),
            'search-tools': StaticCategory(id=13, name=_('Search Tools')),
            'shopping': StaticCategory(id=141, name=_('Shopping')),
            'social-communication': StaticCategory(
                id=71, name=_('Social & Communication')),
            'tabs': StaticCategory(id=93, name=_('Tabs')),
            'web-development': StaticCategory(id=4, name=_('Web Development')),
            'other': StaticCategory(id=73, name=_('Other'))
        }),
        ADDON_THEME: SortedDict({
            'animals': StaticCategory(id=30, name=_('Animals')),
            'compact': StaticCategory(id=32, name=_('Compact')),
            'large': StaticCategory(id=67, name=_('Large')),
            'miscellaneous': StaticCategory(id=21, name=_('Miscellaneous')),
            'modern': StaticCategory(id=62, name=_('Modern')),
            'nature': StaticCategory(id=29, name=_('Nature')),
            'os-integration': StaticCategory(id=61, name=_('OS Integration')),
            'retro': StaticCategory(id=31, name=_('Retro')),
            'sports': StaticCategory(id=26, name=_('Sports'))
        }),
        ADDON_DICT: {
            'general': StaticCategory(id=95, name=_('General'))
        },
        ADDON_SEARCH: SortedDict({
            'bookmarks': StaticCategory(id=79, name=_('Bookmarks')),
            'business': StaticCategory(id=80, name=_('Business')),
            'dictionaries-encyclopedias': StaticCategory(
                id=81, name=_('Dictionaries & Encyclopedias')),
            'general': StaticCategory(id=82, name=_('General')),
            'kids': StaticCategory(id=83, name=_('Kids')),
            'multiple-search': StaticCategory(
                id=84, name=_('Multiple Search')),
            'music': StaticCategory(id=85, name=_('Music')),
            'news-blogs': StaticCategory(id=86, name=_('News & Blogs')),
            'photos-images': StaticCategory(id=87, name=_('Photos & Images')),
            'shopping-e-commerce': StaticCategory(
                id=88, name=_('Shopping & E-Commerce')),
            'social-people': StaticCategory(id=89, name=_('Social & People')),
            'sports': StaticCategory(id=90, name=_('Sports')),
            'travel': StaticCategory(id=91, name=_('Travel')),
            'video': StaticCategory(id=78, name=_('Video'))
        }),
        ADDON_LPAPP: {
            'general': StaticCategory(id=98, name=_('General'))
        },
        ADDON_PERSONA: SortedDict({
            'abstract': StaticCategory(id=100, name=_('Abstract')),
            'causes': StaticCategory(id=120, name=_('Causes')),
            'fashion': StaticCategory(id=124, name=_('Fashion')),
            'film-and-tv': StaticCategory(id=126, name=_('Film and TV')),
            'firefox': StaticCategory(id=108, name=_('Firefox')),
            'foxkeh': StaticCategory(id=110, name=_('Foxkeh')),
            'holiday': StaticCategory(id=128, name=_('Holiday')),
            'music': StaticCategory(id=122, name=_('Music')),
            'nature': StaticCategory(id=102, name=_('Nature')),
            'other': StaticCategory(id=114, name=_('Other')),
            'scenery': StaticCategory(id=106, name=_('Scenery')),
            'seasonal': StaticCategory(id=112, name=_('Seasonal')),
            'solid': StaticCategory(id=118, name=_('Solid')),
            'sports': StaticCategory(id=104, name=_('Sports')),
            'websites': StaticCategory(id=116, name=_('Websites'))
        })
    }),
    ANDROID.id: SortedDict({
        ADDON_EXTENSION: {
            'device-features-location': StaticCategory(
                id=145, name=_('Device Features & Location')),
            'experimental': StaticCategory(id=151, name=_('Experimental')),
            'feeds-news-blogging': StaticCategory(
                id=147, name=_('Feeds, News, & Blogging')),
            'performance': StaticCategory(id=144, name=_('Performance')),
            'photos-media': StaticCategory(id=143, name=_('Photos & Media')),
            'security-privacy': StaticCategory(
                id=149, name=_('Security & Privacy')),
            'shopping': StaticCategory(id=150, name=_('Shopping')),
            'social-networking': StaticCategory(
                id=148, name=_('Social Networking')),
            'sports-games': StaticCategory(id=146, name=_('Sports & Games')),
            'user-interface': StaticCategory(id=152, name=_('User Interface'))
        }
    }),
    # Fennec (old)
    MOBILE.id: SortedDict({
        ADDON_EXTENSION: SortedDict({
            'device-features-location': StaticCategory(
                id=137, name=_('Device Features & Location')),
            'experimental': StaticCategory(id=94, name=_('Experimental')),
            'feeds-news-blogging': StaticCategory(
                id=135, name=_('Feeds, News & Blogging')),
            'performance': StaticCategory(id=138, name=_('Performance')),
            'photos-media': StaticCategory(id=139, name=_('Photos & Media')),
            'security-privacy': StaticCategory(
                id=132, name=_('Security & Privacy')),
            'shopping': StaticCategory(id=133, name=_('Shopping')),
            'social-networking': StaticCategory(
                id=134, name=_('Social Networking')),
            'sports-games': StaticCategory(id=136, name=_('Sports & Games')),
            'user-interface': StaticCategory(id=131, name=_('User Interface'))
        })
    }),
    THUNDERBIRD.id: SortedDict({
        ADDON_EXTENSION: SortedDict({
            'appearance': StaticCategory(
                id=208, name=_('Appearance and Customization')),
            'calendar': StaticCategory(
                id=204, name=_('Calendar and Date/Time')),
            'chat': StaticCategory(id=210, name=_('Chat and IM')),
            'composition': StaticCategory(
                id=202, name=_('Message Composition')),
            'contacts': StaticCategory(id=23, name=_('Contacts')),
            'folders-and-filters': StaticCategory(
                id=200, name=_('Folders and Filters')),
            'importexport': StaticCategory(id=206, name=_('Import/Export')),
            'language-support': StaticCategory(
                id=69, name=_('Language Support')),
            'message-and-news-reading': StaticCategory(
                id=58, name=_('Message and News Reading')),
            'miscellaneous': StaticCategory(id=50, name=_('Miscellaneous')),
            'privacy-and-security': StaticCategory(
                id=66, name=_('Privacy and Security')),
            'tags': StaticCategory(id=212, name=_('Tags'))
        }),
        ADDON_THEME: SortedDict({
            'compact': StaticCategory(id=64, name=_('Compact')),
            'miscellaneous': StaticCategory(id=60, name=_('Miscellaneous')),
            'modern': StaticCategory(id=63, name=_('Modern')),
            'nature': StaticCategory(id=65, name=_('Nature'))
        }),
        ADDON_DICT: {
            'general': StaticCategory(id=97, name=_('General'))
        },
        ADDON_LPAPP: {
            'general': StaticCategory(id=99, name=_('General'))
        }
    }),
    SEAMONKEY.id: SortedDict({
        ADDON_EXTENSION: {
            'bookmarks': StaticCategory(id=51, name=_('Bookmarks')),
            'downloading-and-file-management': StaticCategory(
                id=42, name=_('Downloading and File Management')),
            'interface-customizations': StaticCategory(
                id=48, name=_('Interface Customizations')),
            'language-support-and-translation': StaticCategory(
                id=55, name=_('Language Support and Translation')),
            'miscellaneous': StaticCategory(
                id=49, name=_('Miscellaneous')),
            'photos-and-media': StaticCategory(
                id=56, name=_('Photos and Media')),
            'privacy-and-security': StaticCategory(
                id=46, name=_('Privacy and Security')),
            'rss-news-and-blogging': StaticCategory(
                id=39, name=_('RSS, News and Blogging')),
            'search-tools': StaticCategory(id=47, name=_('Search Tools')),
            'site-specific': StaticCategory(id=52, name=_('Site-specific')),
            'web-and-developer-tools': StaticCategory(
                id=41, name=_('Web and Developer Tools'))
        },
        ADDON_THEME: {
            'miscellaneous': StaticCategory(id=59, name=_('Miscellaneous'))
        },
        ADDON_DICT: {
            'general': StaticCategory(id=96, name=_('General'))
        },
        ADDON_LPAPP: {
            'general': StaticCategory(id=130, name=_('General'))
        }
    }),
}
