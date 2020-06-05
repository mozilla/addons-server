# -*- coding: utf-8 -*-
import copy

from functools import total_ordering

from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.translation import ugettext_lazy as _

from olympia.constants.applications import ANDROID, FIREFOX
from olympia.constants.base import (
    ADDON_DICT, ADDON_EXTENSION, ADDON_LPAPP, ADDON_SEARCH,
    ADDON_SLUGS, ADDON_STATICTHEME, _ADDON_THEME, _ADDON_PERSONA)


@total_ordering
class StaticCategory(object):
    """Helper to populate `CATEGORIES` and provide some helpers.

    Note that any instance is immutable to avoid changing values
    on the globally unique instances during test runs which can lead
    to hard to debug sporadic test-failures.
    """

    def __init__(self, name=None, description=None, weight=0):
        # Avoid triggering our own __setattr__ implementation
        # to keep immutability intact but set initial values.
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'weight', weight)
        object.__setattr__(self, 'description', description)

    def __str__(self):
        return str(self.name)

    def __repr__(self):
        return '<%s: %s (%s)>' % (
            self.__class__.__name__, force_bytes(self), self.application)

    def __eq__(self, other):
        return (
            self.__class__ == other.__class__ and
            self.__dict__ == other.__dict__)

    def __lt__(self, other):
        return (self.weight, self.name) < (other.weight, other.name)

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


CATEGORIES_NO_APP = {
    ADDON_EXTENSION: {
        'alerts-updates': StaticCategory(
            name=_(u'Alerts & Updates'),
            description=_(
                u'Download Firefox extensions that help you stay '
                u'up-to-date, track tasks, improve efficiency. Find '
                u'extensions that reload tabs, manage productivity, and '
                u'more.'
            )
        ),
        'appearance': StaticCategory(
            name=_(u'Appearance'),
            description=_(
                u'Download extensions that modify the appearance of '
                u'websites and the browser Firefox. This category '
                u'includes extensions for dark themes, tab management, '
                u'and more.'
            )
        ),
        'bookmarks': StaticCategory(
            name=_(u'Bookmarks'),
            description=_(
                u'Download extensions that enhance bookmarks by '
                u'password-protecting them, searching for duplicates, '
                u'finding broken bookmarks, and more.'
            )
        ),
        'download-management': StaticCategory(
            name=_(u'Download Management'),
            description=_(
                u'Download Firefox extensions that can help download web, '
                u'music and video content. You can also find extensions '
                u'to manage downloads, share files, and more.'
            )
        ),
        'feeds-news-blogging': StaticCategory(
            name=_(u'Feeds, News & Blogging'),
            description=_(
                u'Download Firefox extensions that remove clutter so you '
                u'can stay up-to-date on social media, catch up on blogs, '
                u'RSS feeds, reduce eye strain, and more.'
            )
        ),
        'games-entertainment': StaticCategory(
            name=_(u'Games & Entertainment'),
            description=_(
                u'Download Firefox extensions to boost your entertainment '
                u'experience. This category includes extensions that can '
                u'enhance gaming, control video playback, and more.'
            )
        ),
        'language-support': StaticCategory(
            name=_(u'Language Support'),
            description=_(
                u'Download Firefox extensions that offer language support '
                u'like grammar check, look-up words, translate text, '
                u'provide text-to-speech, and more.'
            )
        ),
        'photos-music-videos': StaticCategory(
            name=_(u'Photos, Music & Videos'),
            description=_(
                u'Download Firefox extensions that enhance photo, music '
                u'and video experiences. Extensions in this category '
                u'modify audio and video, reverse image search, and more.'
            )
        ),
        'privacy-security': StaticCategory(
            name=_(u'Privacy & Security'),
            description=_(
                u'Download Firefox extensions to browse privately and '
                u'securely. This category includes extensions to block '
                u'annoying ads, prevent tracking, manage redirects, and '
                u'more.'
            )
        ),
        'search-tools': StaticCategory(
            name=_(u'Search Tools'),
            description=_(
                u'Download Firefox extensions for search and look-up. '
                u'This category includes extensions that highlight and '
                u'search text, lookup IP addresses/domains, and more.'
            )
        ),
        'shopping': StaticCategory(
            name=_(u'Shopping'),
            description=_(
                u'Download Firefox extensions that can enhance your '
                u'online shopping experience with coupon finders, deal '
                u'finders, review analyzers, more.'
            )
        ),
        'social-communication': StaticCategory(
            name=_(u'Social & Communication'),
            description=_(
                u'Download Firefox extensions to enhance social media and '
                u'instant messaging. This category includes improved tab '
                u'notifications, video downloaders, and more.'
            )
        ),
        'tabs': StaticCategory(
            name=_(u'Tabs'),
            description=_(
                u'Download Firefox extension to customize tabs and the '
                u'new tab page. Discover extensions that can control '
                u'tabs, change the way you interact with them, and more.'
            )
        ),
        'web-development': StaticCategory(
            name=_(u'Web Development'),
            description=_(
                u'Download Firefox extensions that feature web '
                u'development tools. This category includes extensions '
                u'for GitHub, user agent switching, cookie management, '
                u'and more.'
            )
        ),
        'other': StaticCategory(
            name=_(u'Other'),
            weight=333,
            description=_(
                u'Download Firefox extensions that can be unpredictable '
                u'and creative, yet useful for those odd tasks.'
            )
        ),
        # Android only categories:
        'device-features-location': StaticCategory(
            name=_(u'Device Features & Location'),
            description=_(
                u'Download extensions to enhance Firefox for Android. '
                u'Perform quick searches, free up system resources, take '
                u'notes, and more.'
            )
        ),
        'experimental': StaticCategory(
            name=_(u'Experimental'),
            description=_(
                u'Download Firefox extensions that are regularly updated '
                u'and ready for public testing. Your feedback informs '
                u'developers on changes to make in upcoming versions.'
            )
        ),
        'performance': StaticCategory(
            name=_(u'Performance'),
            description=_(
                u'Download extensions that give Firefox a performance '
                u'boost. Find extensions that help you be more productive '
                u'and efficient by blocking annoying ads and more.'
            )
        ),
        'photos-media': StaticCategory(
            name=_(u'Photos & Media'),
            description=_(
                u'Download Firefox extensions to enhance photos and '
                u'media. This category includes extensions to reverse '
                u'search images, capture full page screenshots, and more.'
            )
        ),
        'security-privacy': StaticCategory(
            name=_(u'Security & Privacy'),
            description=_(
                u'Download Firefox extensions to surf safely and '
                u'privately. Discover extensions that can stop sneaky ad '
                u'trackers in their tracks, easily clear browsing '
                u'history, and more.'
            )
        ),
        'social-networking': StaticCategory(
            name=_(u'Social Networking'),
            description=_(
                u'Download Firefox extensions to enhance your experience '
                u'on popular social networking websites such as YouTube, '
                u'GitHub, Reddit, and more.'
            )
        ),
        'sports-games': StaticCategory(
            name=_(u'Sports & Games'),
            description=_(
                u'Download Firefox extensions to give your entertainment '
                u'experience a boost with live stream enhancers, sports '
                u'updates, and more.'
            )
        ),
        'user-interface': StaticCategory(
            name=_(u'User Interface'),
            description=_(
                u'Download user interface Firefox extensions to alter web '
                u'pages for easier reading, searching, browsing, and more.'
            )
        ),
    },
    _ADDON_THEME: {
        'animals': StaticCategory(name=_(u'Animals')),
        'compact': StaticCategory(name=_(u'Compact')),
        'large': StaticCategory(name=_(u'Large')),
        'miscellaneous': StaticCategory(name=_(u'Miscellaneous')),
        'modern': StaticCategory(name=_(u'Modern')),
        'nature': StaticCategory(name=_(u'Nature')),
        'os-integration': StaticCategory(name=_(u'OS Integration')),
        'retro': StaticCategory(name=_(u'Retro')),
        'sports': StaticCategory(name=_(u'Sports'))
    },
    ADDON_STATICTHEME: {
        'abstract': StaticCategory(
            name=_(u'Abstract'),
            description=_(
                u'Download Firefox artistic and conceptual themes. This '
                u'category includes colorful palettes and shapes, fantasy '
                u'landscapes, playful cats, psychedelic flowers.'
            )
        ),
        'causes': StaticCategory(
            name=_(u'Causes'),
            description=_(
                u'Download Firefox themes for niche interests and topics. '
                u'This category includes sports themes, holidays, '
                u'philanthropic causes, nationalities, and much more.'
            )
        ),
        'fashion': StaticCategory(
            name=_(u'Fashion'),
            description=_(
                u'Download Firefox themes that celebrate style of all '
                u'forms—patterns, florals, textures, models, and more.'
            )
        ),
        'film-and-tv': StaticCategory(
            name=_(u'Film and TV'),
            description=_(
                u'Download Firefox themes with movies and television. '
                u'This category includes anime like Uchiha Madara, movies '
                u'like The Matrix, shows (Game of Thrones), and more.'
            )
        ),
        'firefox': StaticCategory(
            name=_(u'Firefox'),
            description=_(
                u'Download Firefox themes with the Firefox browser theme. '
                u'This category includes colorful, diverse depictions of '
                u'the Firefox logo, including more general fox themes.'
            )
        ),
        'foxkeh': StaticCategory(
            name=_(u'Foxkeh'),
            description=_(
                u'Download Firefox themes with the Japanese Firefox. This '
                u'category includes themes that depict the cute Foxkeh '
                u'mascot in various poses on diverse landscapes.'
            )
        ),
        'holiday': StaticCategory(
            name=_(u'Holiday'),
            description=_(
                u'Download Firefox themes with holidays. This category '
                u'includes Christmas, Halloween, Thanksgiving, St. '
                u'Patrick’s Day, Easter, Fourth of July, and more.'
            )
        ),
        'music': StaticCategory(
            name=_(u'Music'),
            description=_(
                u'Download Firefox themes for musical interests and '
                u'artists. This category includes popular bands like '
                u'Nirvana and BTS, instruments, music videos, and much '
                u'more.'
            )
        ),
        'nature': StaticCategory(
            name=_(u'Nature'),
            description=_(
                u'Download Firefox themes with animals and natural '
                u'landscapes. This category includes flowers, sunsets, '
                u'foxes, seasons, planets, kittens, birds, and more.'
            )
        ),
        'other': StaticCategory(
            name=_(u'Other'),
            weight=333,
            description=_(
                u'Download Firefox themes that are interesting, creative, '
                u'and unique.'
            )
        ),
        'scenery': StaticCategory(
            name=_(u'Scenery'),
            description=_(
                u'Download Firefox themes that feature the environment '
                u'and the natural world. This category includes sunsets, '
                u'beaches, illustrations, city skylines, and more.'
            )
        ),
        'seasonal': StaticCategory(
            name=_(u'Seasonal'),
            description=_(
                u'Download Firefox themes for all four seasons—fall, '
                u'winter, spring, and summer. Autumn leaves, snowy '
                u'mountain peaks, sunny summer days, and spring flowers.'
            )
        ),
        'solid': StaticCategory(
            name=_(u'Solid'),
            description=_(
                u'Download Firefox themes with solid and gradient colors '
                u'to personalize your browser. This category includes '
                u'bold reds, pastels, soft greys, and much more.'
            )
        ),
        'sports': StaticCategory(
            name=_(u'Sports'),
            description=_(
                u'Download Firefox themes that feature a variety of '
                u'sports. This category includes country flags, sports '
                u'teams, soccer, hockey, and more.'
            )
        ),
        'websites': StaticCategory(
            name=_(u'Websites'),
            description=_(
                u'Download Firefox themes that capture the essence of the '
                u'web—captivating, unusual, and distinctive.'
            )
        )
    },
    ADDON_DICT: {
        'general': StaticCategory(name=_(u'General'))
    },
    ADDON_SEARCH: {
        'bookmarks': StaticCategory(name=_(u'Bookmarks')),
        'business': StaticCategory(name=_(u'Business')),
        'dictionaries-encyclopedias': StaticCategory(
            name=_(u'Dictionaries & Encyclopedias')),
        'general': StaticCategory(name=_(u'General')),
        'kids': StaticCategory(name=_(u'Kids')),
        'multiple-search': StaticCategory(name=_(u'Multiple Search')),
        'music': StaticCategory(name=_(u'Music')),
        'news-blogs': StaticCategory(name=_(u'News & Blogs')),
        'photos-images': StaticCategory(name=_(u'Photos & Images')),
        'shopping-e-commerce': StaticCategory(
            name=_(u'Shopping & E-Commerce')),
        'social-people': StaticCategory(name=_(u'Social & People')),
        'sports': StaticCategory(name=_(u'Sports')),
        'travel': StaticCategory(name=_(u'Travel')),
        'video': StaticCategory(name=_(u'Video'))
    },
    ADDON_LPAPP: {
        'general': StaticCategory(name=_(u'General'))
    },
}

CATEGORIES_NO_APP[_ADDON_PERSONA] = {
    slug: copy.copy(cat)
    for slug, cat in CATEGORIES_NO_APP[ADDON_STATICTHEME].items()}

for type_ in CATEGORIES_NO_APP:
    for slug, cat in CATEGORIES_NO_APP[type_].items():
        # Flatten some values and set them, avoiding immutability
        # of `StaticCategory` by calling `object.__setattr__` directly.
        object.__setattr__(cat, 'slug', slug)
        object.__setattr__(cat, 'type', type_)
        object.__setattr__(cat, 'misc', slug in ('miscellaneous', 'other'))


# These numbers are ids for Category model instances in the database.
# For existing categories they MUST match, for the fk in AddonCategory to work.
# To add a category to an app you can use any unused id (needs a migration too)
CATEGORIES = {
    FIREFOX.id: {
        ADDON_EXTENSION: {
            'alerts-updates': 72,
            'appearance': 14,
            'bookmarks': 22,
            'download-management': 5,
            'feeds-news-blogging': 1,
            'games-entertainment': 142,
            'language-support': 37,
            'photos-music-videos': 38,
            'privacy-security': 12,
            'search-tools': 13,
            'shopping': 141,
            'social-communication': 71,
            'tabs': 93,
            'web-development': 4,
            'other': 73,
        },
        ADDON_STATICTHEME: {
            'abstract': 300,
            'causes': 320,
            'fashion': 324,
            'film-and-tv': 326,
            'firefox': 308,
            'foxkeh': 310,
            'holiday': 328,
            'music': 322,
            'nature': 302,
            'other': 314,
            'scenery': 306,
            'seasonal': 312,
            'solid': 318,
            'sports': 304,
            'websites': 316,
        },
        ADDON_LPAPP: {
            'general': 98,
        },
        ADDON_DICT: {
            'general': 95,
        },
    },
    ANDROID.id: {
        ADDON_EXTENSION: {
            'device-features-location': 145,
            'experimental': 151,
            'feeds-news-blogging': 147,
            'performance': 144,
            'photos-media': 143,
            'security-privacy': 149,
            'shopping': 150,
            'social-networking': 148,
            'sports-games': 146,
            'user-interface': 152,
            'other': 153,
        },
        ADDON_STATICTHEME: {
            'abstract': 400,
            'causes': 420,
            'fashion': 424,
            'film-and-tv': 426,
            'firefox': 408,
            'foxkeh': 410,
            'holiday': 428,
            'music': 422,
            'nature': 402,
            'other': 414,
            'scenery': 406,
            'seasonal': 412,
            'solid': 418,
            'sports': 404,
            'websites': 416,
        },
    },
}


CATEGORIES_BY_ID = {}

for app in CATEGORIES:
    for type_ in CATEGORIES[app]:
        for slug, id_ in CATEGORIES[app][type_].items():
            cat = copy.copy(CATEGORIES_NO_APP[type_][slug])
            # Flatten some values and set them, avoiding immutability
            # of `StaticCategory` by calling `object.__setattr__` directly.
            object.__setattr__(cat, 'id', id_)
            object.__setattr__(cat, 'application', app)
            CATEGORIES_BY_ID[id_] = cat
            CATEGORIES[app][type_][slug] = cat
