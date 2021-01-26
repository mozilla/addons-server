# -*- coding: utf-8 -*-
import copy

from functools import total_ordering

from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.translation import ugettext_lazy as _

from olympia.constants.applications import ANDROID, FIREFOX
from olympia.constants.base import (
    ADDON_DICT,
    ADDON_EXTENSION,
    ADDON_LPAPP,
    _ADDON_SEARCH,
    ADDON_SLUGS,
    ADDON_STATICTHEME,
    _ADDON_THEME,
    _ADDON_PERSONA,
)


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
            self.__class__.__name__,
            force_bytes(self),
            self.application,
        )

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.__dict__ == other.__dict__

    def __lt__(self, other):
        return (self.weight, self.name) < (other.weight, other.name)

    def get_url_path(self):
        try:
            type = ADDON_SLUGS[self.type]
        except KeyError:
            type = ADDON_SLUGS[ADDON_EXTENSION]
        return reverse('browse.%s' % type, args=[self.slug])

    def _immutable(self, *args):
        raise TypeError('%r instances are immutable' % self.__class__.__name__)

    __setattr__ = __delattr__ = _immutable
    del _immutable


CATEGORIES_NO_APP = {
    ADDON_EXTENSION: {
        'alerts-updates': StaticCategory(
            name=_('Alerts & Updates'),
            description=_(
                'Download Firefox extensions that help you stay '
                'up-to-date, track tasks, improve efficiency. Find '
                'extensions that reload tabs, manage productivity, and '
                'more.'
            ),
        ),
        'appearance': StaticCategory(
            name=_('Appearance'),
            description=_(
                'Download extensions that modify the appearance of '
                'websites and the browser Firefox. This category '
                'includes extensions for dark themes, tab management, '
                'and more.'
            ),
        ),
        'bookmarks': StaticCategory(
            name=_('Bookmarks'),
            description=_(
                'Download extensions that enhance bookmarks by '
                'password-protecting them, searching for duplicates, '
                'finding broken bookmarks, and more.'
            ),
        ),
        'download-management': StaticCategory(
            name=_('Download Management'),
            description=_(
                'Download Firefox extensions that can help download web, '
                'music and video content. You can also find extensions '
                'to manage downloads, share files, and more.'
            ),
        ),
        'feeds-news-blogging': StaticCategory(
            name=_('Feeds, News & Blogging'),
            description=_(
                'Download Firefox extensions that remove clutter so you '
                'can stay up-to-date on social media, catch up on blogs, '
                'RSS feeds, reduce eye strain, and more.'
            ),
        ),
        'games-entertainment': StaticCategory(
            name=_('Games & Entertainment'),
            description=_(
                'Download Firefox extensions to boost your entertainment '
                'experience. This category includes extensions that can '
                'enhance gaming, control video playback, and more.'
            ),
        ),
        'language-support': StaticCategory(
            name=_('Language Support'),
            description=_(
                'Download Firefox extensions that offer language support '
                'like grammar check, look-up words, translate text, '
                'provide text-to-speech, and more.'
            ),
        ),
        'photos-music-videos': StaticCategory(
            name=_('Photos, Music & Videos'),
            description=_(
                'Download Firefox extensions that enhance photo, music '
                'and video experiences. Extensions in this category '
                'modify audio and video, reverse image search, and more.'
            ),
        ),
        'privacy-security': StaticCategory(
            name=_('Privacy & Security'),
            description=_(
                'Download Firefox extensions to browse privately and '
                'securely. This category includes extensions to block '
                'annoying ads, prevent tracking, manage redirects, and '
                'more.'
            ),
        ),
        'search-tools': StaticCategory(
            name=_('Search Tools'),
            description=_(
                'Download Firefox extensions for search and look-up. '
                'This category includes extensions that highlight and '
                'search text, lookup IP addresses/domains, and more.'
            ),
        ),
        'shopping': StaticCategory(
            name=_('Shopping'),
            description=_(
                'Download Firefox extensions that can enhance your '
                'online shopping experience with coupon finders, deal '
                'finders, review analyzers, more.'
            ),
        ),
        'social-communication': StaticCategory(
            name=_('Social & Communication'),
            description=_(
                'Download Firefox extensions to enhance social media and '
                'instant messaging. This category includes improved tab '
                'notifications, video downloaders, and more.'
            ),
        ),
        'tabs': StaticCategory(
            name=_('Tabs'),
            description=_(
                'Download Firefox extension to customize tabs and the '
                'new tab page. Discover extensions that can control '
                'tabs, change the way you interact with them, and more.'
            ),
        ),
        'web-development': StaticCategory(
            name=_('Web Development'),
            description=_(
                'Download Firefox extensions that feature web '
                'development tools. This category includes extensions '
                'for GitHub, user agent switching, cookie management, '
                'and more.'
            ),
        ),
        'other': StaticCategory(
            name=_('Other'),
            weight=333,
            description=_(
                'Download Firefox extensions that can be unpredictable '
                'and creative, yet useful for those odd tasks.'
            ),
        ),
        # Android only categories:
        'device-features-location': StaticCategory(
            name=_('Device Features & Location'),
            description=_(
                'Download extensions to enhance Firefox for Android. '
                'Perform quick searches, free up system resources, take '
                'notes, and more.'
            ),
        ),
        'experimental': StaticCategory(
            name=_('Experimental'),
            description=_(
                'Download Firefox extensions that are regularly updated '
                'and ready for public testing. Your feedback informs '
                'developers on changes to make in upcoming versions.'
            ),
        ),
        'performance': StaticCategory(
            name=_('Performance'),
            description=_(
                'Download extensions that give Firefox a performance '
                'boost. Find extensions that help you be more productive '
                'and efficient by blocking annoying ads and more.'
            ),
        ),
        'photos-media': StaticCategory(
            name=_('Photos & Media'),
            description=_(
                'Download Firefox extensions to enhance photos and '
                'media. This category includes extensions to reverse '
                'search images, capture full page screenshots, and more.'
            ),
        ),
        'security-privacy': StaticCategory(
            name=_('Security & Privacy'),
            description=_(
                'Download Firefox extensions to surf safely and '
                'privately. Discover extensions that can stop sneaky ad '
                'trackers in their tracks, easily clear browsing '
                'history, and more.'
            ),
        ),
        'social-networking': StaticCategory(
            name=_('Social Networking'),
            description=_(
                'Download Firefox extensions to enhance your experience '
                'on popular social networking websites such as YouTube, '
                'GitHub, Reddit, and more.'
            ),
        ),
        'sports-games': StaticCategory(
            name=_('Sports & Games'),
            description=_(
                'Download Firefox extensions to give your entertainment '
                'experience a boost with live stream enhancers, sports '
                'updates, and more.'
            ),
        ),
        'user-interface': StaticCategory(
            name=_('User Interface'),
            description=_(
                'Download user interface Firefox extensions to alter web '
                'pages for easier reading, searching, browsing, and more.'
            ),
        ),
    },
    _ADDON_THEME: {
        'animals': StaticCategory(name=_('Animals')),
        'compact': StaticCategory(name=_('Compact')),
        'large': StaticCategory(name=_('Large')),
        'miscellaneous': StaticCategory(name=_('Miscellaneous')),
        'modern': StaticCategory(name=_('Modern')),
        'nature': StaticCategory(name=_('Nature')),
        'os-integration': StaticCategory(name=_('OS Integration')),
        'retro': StaticCategory(name=_('Retro')),
        'sports': StaticCategory(name=_('Sports')),
    },
    ADDON_STATICTHEME: {
        'abstract': StaticCategory(
            name=_('Abstract'),
            description=_(
                'Download Firefox artistic and conceptual themes. This '
                'category includes colorful palettes and shapes, fantasy '
                'landscapes, playful cats, psychedelic flowers.'
            ),
        ),
        'causes': StaticCategory(
            name=_('Causes'),
            description=_(
                'Download Firefox themes for niche interests and topics. '
                'This category includes sports themes, holidays, '
                'philanthropic causes, nationalities, and much more.'
            ),
        ),
        'fashion': StaticCategory(
            name=_('Fashion'),
            description=_(
                'Download Firefox themes that celebrate style of all '
                'forms—patterns, florals, textures, models, and more.'
            ),
        ),
        'film-and-tv': StaticCategory(
            name=_('Film and TV'),
            description=_(
                'Download Firefox themes with movies and television. '
                'This category includes anime like Uchiha Madara, movies '
                'like The Matrix, shows (Game of Thrones), and more.'
            ),
        ),
        'firefox': StaticCategory(
            name=_('Firefox'),
            description=_(
                'Download Firefox themes with the Firefox browser theme. '
                'This category includes colorful, diverse depictions of '
                'the Firefox logo, including more general fox themes.'
            ),
        ),
        'foxkeh': StaticCategory(
            name=_('Foxkeh'),
            description=_(
                'Download Firefox themes with the Japanese Firefox. This '
                'category includes themes that depict the cute Foxkeh '
                'mascot in various poses on diverse landscapes.'
            ),
        ),
        'holiday': StaticCategory(
            name=_('Holiday'),
            description=_(
                'Download Firefox themes with holidays. This category '
                'includes Christmas, Halloween, Thanksgiving, St. '
                'Patrick’s Day, Easter, Fourth of July, and more.'
            ),
        ),
        'music': StaticCategory(
            name=_('Music'),
            description=_(
                'Download Firefox themes for musical interests and '
                'artists. This category includes popular bands like '
                'Nirvana and BTS, instruments, music videos, and much '
                'more.'
            ),
        ),
        'nature': StaticCategory(
            name=_('Nature'),
            description=_(
                'Download Firefox themes with animals and natural '
                'landscapes. This category includes flowers, sunsets, '
                'foxes, seasons, planets, kittens, birds, and more.'
            ),
        ),
        'other': StaticCategory(
            name=_('Other'),
            weight=333,
            description=_(
                'Download Firefox themes that are interesting, creative, and unique.'
            ),
        ),
        'scenery': StaticCategory(
            name=_('Scenery'),
            description=_(
                'Download Firefox themes that feature the environment '
                'and the natural world. This category includes sunsets, '
                'beaches, illustrations, city skylines, and more.'
            ),
        ),
        'seasonal': StaticCategory(
            name=_('Seasonal'),
            description=_(
                'Download Firefox themes for all four seasons—fall, '
                'winter, spring, and summer. Autumn leaves, snowy '
                'mountain peaks, sunny summer days, and spring flowers.'
            ),
        ),
        'solid': StaticCategory(
            name=_('Solid'),
            description=_(
                'Download Firefox themes with solid and gradient colors '
                'to personalize your browser. This category includes '
                'bold reds, pastels, soft greys, and much more.'
            ),
        ),
        'sports': StaticCategory(
            name=_('Sports'),
            description=_(
                'Download Firefox themes that feature a variety of '
                'sports. This category includes country flags, sports '
                'teams, soccer, hockey, and more.'
            ),
        ),
        'websites': StaticCategory(
            name=_('Websites'),
            description=_(
                'Download Firefox themes that capture the essence of the '
                'web—captivating, unusual, and distinctive.'
            ),
        ),
    },
    ADDON_DICT: {'general': StaticCategory(name=_('General'))},
    _ADDON_SEARCH: {
        'bookmarks': StaticCategory(name=_('Bookmarks')),
        'business': StaticCategory(name=_('Business')),
        'dictionaries-encyclopedias': StaticCategory(
            name=_('Dictionaries & Encyclopedias')
        ),
        'general': StaticCategory(name=_('General')),
        'kids': StaticCategory(name=_('Kids')),
        'multiple-search': StaticCategory(name=_('Multiple Search')),
        'music': StaticCategory(name=_('Music')),
        'news-blogs': StaticCategory(name=_('News & Blogs')),
        'photos-images': StaticCategory(name=_('Photos & Images')),
        'shopping-e-commerce': StaticCategory(name=_('Shopping & E-Commerce')),
        'social-people': StaticCategory(name=_('Social & People')),
        'sports': StaticCategory(name=_('Sports')),
        'travel': StaticCategory(name=_('Travel')),
        'video': StaticCategory(name=_('Video')),
    },
    ADDON_LPAPP: {'general': StaticCategory(name=_('General'))},
}

CATEGORIES_NO_APP[_ADDON_PERSONA] = {
    slug: copy.copy(cat) for slug, cat in CATEGORIES_NO_APP[ADDON_STATICTHEME].items()
}

for type_ in CATEGORIES_NO_APP:
    for slug, cat in CATEGORIES_NO_APP[type_].items():
        # Flatten some values and set them, avoiding immutability
        # of `StaticCategory` by calling `object.__setattr__` directly.
        object.__setattr__(cat, 'slug', slug)
        object.__setattr__(cat, 'type', type_)
        object.__setattr__(cat, 'misc', slug in ('miscellaneous', 'other'))


# These category ids are used in AddonCategory. To add a category to an app you can use
# any unused id.
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
