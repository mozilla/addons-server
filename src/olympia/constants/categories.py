from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

from olympia.constants.applications import ANDROID, FIREFOX
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
                id=72,
                name=_(u'Alerts & Updates'),
                description=_(
                    u'Find Firefox extensions that help you stay up-to-date, '
                    u'remember tasks, and improve efficiency. This category '
                    u'includes extensions that can automatically reload tabs, '
                    u'manage productivity, and more.'
                )
            ),
            'appearance': StaticCategory(
                id=14,
                name=_(u'Appearance'),
                description=_(
                    u'Explore extensions that can modify the appearance of '
                    u'websites and Firefox. This category includes extensions '
                    u'for dark themes, tab arrangements, and more.'
                )
            ),
            'bookmarks': StaticCategory(
                id=22,
                name=_(u'Bookmarks'),
                description=_(
                    u'Discover extensions that enhance bookmarks by '
                    u'password-protecting them, searching for duplicates, '
                    u'finding broken bookmarks, and more.'
                )
            ),
            'download-management': StaticCategory(
                id=5,
                name=_(u'Download Management'),
                description=_(
                    u'Get Firefox extensions that can help download web, '
                    u'music and video content. You can also find extensions '
                    u'to manage downloads, share files, and more.'
                )
            ),
            'feeds-news-blogging': StaticCategory(
                id=1,
                name=_(u'Feeds, News & Blogging'),
                description=_(
                    u'Firefox extensions that remove clutter so you can stay '
                    u'up-to-date on social media, catch up on blogs, RSS '
                    u'feeds, reduce eye strain, and more.'
                )
            ),
            'games-entertainment': StaticCategory(
                id=142,
                name=_(u'Games & Entertainment'),
                description=_(
                    u'Firefox extensions to help tackle slow days and boost '
                    u'your entertainment experience. This category includes '
                    u'extensions that can enhance gaming, control video '
                    u'playback, and more.'
                )
            ),
            'language-support': StaticCategory(
                id=37,
                name=_(u'Language Support'),
                description=_(
                    u'Find Firefox extensions that can grammar check, look-up '
                    u'words, translate text, provide text-to-speech, and more.'
                )
            ),
            'photos-music-videos': StaticCategory(
                id=38,
                name=_(u'Photos, Music & Videos'),
                description=_(
                    u'Find Firefox extensions that can enhance your photo, '
                    u'music and video experiences. Extensions in this '
                    u'category can modify audio and video playback, perform '
                    u'reverse image searches, and more.'
                )
            ),
            'privacy-security': StaticCategory(
                id=12,
                name=_(u'Privacy & Security'),
                description=_(
                    u'Get Firefox extensions to browse privately and '
                    u'securely. This category includes extensions to block '
                    u'ads, prevent tracking, redirects, and more.'
                )
            ),
            'search-tools': StaticCategory(
                id=13,
                name=_(u'Search Tools'),
                description=_(
                    u'Discover Firefox extensions for your search and look-up '
                    u'needs. This category includes extensions that can '
                    u'highlight and search text, lookup IP addresses and '
                    u'domains, and more.'
                )
            ),
            'shopping': StaticCategory(
                id=141,
                name=_(u'Shopping'),
                description=_(
                    u'Discover Firefox extensions that can enhance your '
                    u'online shopping experience with coupon finders, deal '
                    u'finders, review analyzers, more.'
                )
            ),
            'social-communication': StaticCategory(
                id=71,
                name=_(u'Social & Communication'),
                description=_(
                    u'Find Firefox extensions to elevate your experience with '
                    u'social media and instant messaging platforms. This '
                    u'category includes improved tab notifications, video '
                    u'downloaders, and more.'
                )
            ),
            'tabs': StaticCategory(
                id=93,
                name=_(u'Tabs'),
                description=_(
                    u'Stumble on Firefox extension to customize tabs and the '
                    u'new tab page. Discover extensions that can control '
                    u'tabs, change the way you interact with them and more.'
                )
            ),
            'web-development': StaticCategory(
                id=4,
                name=_(u'Web Development'),
                description=_(
                    u'Find Firefox extensions that feature tools for web '
                    u'development. This category includes extensions for '
                    u'GitHub, user agent switching, cookie management, '
                    u'and more.'
                )
            ),
            'other': StaticCategory(
                id=73,
                name=_(u'Other'),
                weight=333,
                description=_(
                    u'Firefox extensions that can be unpredictable and '
                    u'creative, yet useful for those odd tasks.'
                )
            )
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
            'abstract': StaticCategory(
                id=300,
                name=_(u'Abstract'),
                description=_(
                    u'Download Firefox themes that are artistic and '
                    u'conceptual. This category includes themes with colorful '
                    u'palettes and shapes, fantasy landscapes, playful cats, '
                    u'and psychedelic flowers.'
                )
            ),
            'causes': StaticCategory(
                id=320,
                name=_(u'Causes'),
                description=_(
                    u'Download Firefox themes for niche interests and topics. '
                    u'This category includes sports themes, holidays, '
                    u'philanthropic causes, nationalities, and much more.'
                )
            ),
            'fashion': StaticCategory(
                id=324,
                name=_(u'Fashion'),
                description=_(
                    u'Download Firefox themes that celebrate style of all '
                    u'forms—patterns, florals, textures, models, and more.'
                )
            ),
            'film-and-tv': StaticCategory(
                id=326,
                name=_(u'Film and TV'),
                description=_(
                    u'Download Firefox themes that feature movies, television '
                    u'shows, and anime. This category includes themes that '
                    u'depict popular anime like Uchiha Madara, movies like '
                    u'The Matrix, shows like Game of Thrones, and more.'
                )
            ),
            'firefox': StaticCategory(
                id=308,
                name=_(u'Firefox'),
                description=_(
                    u'Download Firefox themes that feature the Firefox '
                    u'browser theme. This category includes themes with '
                    u'colorful, diverse depictions of the Firefox logo, '
                    u'including more general fox themes.'
                )
            ),
            'foxkeh': StaticCategory(
                id=310,
                name=_(u'Foxkeh'),
                description=_(
                    u'Download Firefox themes that feature the Japanese '
                    u'Firefox. This category includes themes that depict the '
                    u'cute Foxkeh mascot in various poses on diverse '
                    u'landscapes.'
                )
            ),
            'holiday': StaticCategory(
                id=328,
                name=_(u'Holiday'),
                description=_(
                    u'Download Firefox themes that feature holidays. This '
                    u'category includes themes for Christmas, Halloween, '
                    u'Thanksgiving, St. Patrick’s Day, Easter, Valentine’s '
                    u'Day, Fourth of July, and more.'
                )
            ),
            'music': StaticCategory(
                id=322,
                name=_(u'Music'),
                description=_(
                    u'Download Firefox themes that feature musical interests '
                    u'and artists. This category includes popular bands like '
                    u'Nirvana, BTS, Pink Floyd, instruments, music videos, '
                    u'instruments, and much more.'
                )
            ),
            'nature': StaticCategory(
                id=302,
                name=_(u'Nature'),
                description=_(
                    u'Download Firefox themes that feature animals and '
                    u'natural landscapes. This category includes themes with '
                    u'flowers, sunsets, foxes, seasonal scenes, night skies, '
                    u'planets, kittens, birds, and more.'
                )
            ),
            'other': StaticCategory(
                id=314,
                name=_(u'Other'),
                weight=333,
                description=_(
                    u'Download Firefox themes that are interesting, creative, '
                    u'and unique.'
                )
            ),
            'scenery': StaticCategory(
                id=306,
                name=_(u'Scenery'),
                description=_(
                    u'Download Firefox themes that feature the environment '
                    u'and the natural world. This category includes themes '
                    u'with sunsets, beaches, illustrations, city skylines, '
                    u'and more.'
                )
            ),
            'seasonal': StaticCategory(
                id=312,
                name=_(u'Seasonal'),
                description=_(
                    u'Download Firefox themes that feature all four seasons '
                    u'of the year—fall, winter, spring, and summer. Autumn '
                    u'leaves, snowy mountain peaks, sunny summer days, and '
                    u'spring flowers.'
                )
            ),
            'solid': StaticCategory(
                id=318,
                name=_(u'Solid'),
                description=_(
                    u'Download Firefox themes that use solid and gradient '
                    u'colors to personalize your browser. This category '
                    u'includes bold reds, pastel washes, soft greys, and '
                    u'much more.'
                )
            ),
            'sports': StaticCategory(
                id=304,
                name=_(u'Sports'),
                description=_(
                    u'Download Firefox themes that feature a variety of '
                    u'sports. This category includes country flags, sports '
                    u'teams, soccer, hockey, and more.'
                )
            ),
            'websites': StaticCategory(
                id=316,
                name=_(u'Websites'),
                description=_(
                    u'Download Firefox themes that capture the essence of the '
                    u'web—captivating, unusual, and distinctive.'
                )
            )
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
            'abstract': StaticCategory(
                id=100,
                name=_(u'Abstract'),
                description=_(
                    u'Download Firefox themes that are artistic and '
                    u'conceptual. This category includes themes with colorful '
                    u'palettes and shapes, fantasy landscapes, playful cats, '
                    u'and psychedelic flowers.'
                )
            ),
            'causes': StaticCategory(
                id=120,
                name=_(u'Causes'),
                description=_(
                    u'Download Firefox themes for niche interests and topics. '
                    u'This category includes sports themes, holidays, '
                    u'philanthropic causes, nationalities, and much more.'
                )
            ),
            'fashion': StaticCategory(
                id=124,
                name=_(u'Fashion'),
                description=_(
                    u'Download Firefox themes that celebrate style of all '
                    u'forms—patterns, florals, textures, models, and more.'
                )
            ),
            'film-and-tv': StaticCategory(
                id=126,
                name=_(u'Film and TV'),
                description=_(
                    u'Download Firefox themes that feature movies, television '
                    u'shows, and anime. This category includes themes that '
                    u'depict popular anime like Uchiha Madara, movies like '
                    u'The Matrix, shows like Game of Thrones, and more.'
                )
            ),
            'firefox': StaticCategory(
                id=108,
                name=_(u'Firefox'),
                description=_(
                    u'Download Firefox themes that feature the Firefox '
                    u'browser theme. This category includes themes with '
                    u'colorful, diverse depictions of the Firefox logo, '
                    u'including more general fox themes.'
                )
            ),
            'foxkeh': StaticCategory(
                id=110,
                name=_(u'Foxkeh'),
                description=_(
                    u'Download Firefox themes that feature the Japanese '
                    u'Firefox. This category includes themes that depict the '
                    u'cute Foxkeh mascot in various poses on diverse '
                    u'landscapes.'
                )
            ),
            'holiday': StaticCategory(
                id=128,
                name=_(u'Holiday'),
                description=_(
                    u'Download Firefox themes that feature holidays. This '
                    u'category includes themes for Christmas, Halloween, '
                    u'Thanksgiving, St. Patrick’s Day, Easter, Valentine’s '
                    u'Day, Fourth of July, and more.'
                )
            ),
            'music': StaticCategory(
                id=122,
                name=_(u'Music'),
                description=_(
                    u'Download Firefox themes that feature musical interests '
                    u'and artists. This category includes popular bands like '
                    u'Nirvana, BTS, Pink Floyd, instruments, music videos, '
                    u'instruments, and much more.'
                )
            ),
            'nature': StaticCategory(
                id=102,
                name=_(u'Nature'),
                description=_(
                    u'Download Firefox themes that feature animals and '
                    u'natural landscapes. This category includes themes with '
                    u'flowers, sunsets, foxes, seasonal scenes, night skies, '
                    u'planets, kittens, birds, and more.'
                )
            ),
            'other': StaticCategory(
                id=114,
                name=_(u'Other'),
                description=_(
                    u'Download Firefox themes that are interesting, creative, '
                    u'and unique.'
                )
            ),
            'scenery': StaticCategory(
                id=106,
                name=_(u'Scenery'),
                description=_(
                    u'Download Firefox themes that feature the environment '
                    u'and the natural world. This category includes themes '
                    u'with sunsets, beaches, illustrations, city skylines, '
                    u'and more.'
                )
            ),
            'seasonal': StaticCategory(
                id=112,
                name=_(u'Seasonal'),
                description=_(
                    u'Download Firefox themes that feature all four seasons '
                    u'of the year—fall, winter, spring, and summer. Autumn '
                    u'leaves, snowy mountain peaks, sunny summer days, and '
                    u'spring flowers.'
                )
            ),
            'solid': StaticCategory(
                id=118,
                name=_(u'Solid'),
                description=_(
                    u'Download Firefox themes that use solid and gradient '
                    u'colors to personalize your browser. This category '
                    u'includes bold reds, pastel washes, soft greys, and '
                    u'much more.'
                )
            ),
            'sports': StaticCategory(
                id=104,
                name=_(u'Sports'),
                description=_(
                    u'Download Firefox themes that feature a variety of '
                    u'sports. This category includes country flags, sports '
                    u'teams, soccer, hockey, and more.'
                )
            ),
            'websites': StaticCategory(
                id=116,
                name=_(u'Websites'),
                description=_(
                    u'Download Firefox themes that capture the essence of the '
                    u'web—captivating, unusual, and distinctive.'
                )
            )
        }
    },
    ANDROID.id: {
        ADDON_EXTENSION: {
            'device-features-location': StaticCategory(
                id=145,
                name=_(u'Device Features & Location'),
                description=_(
                    u'Discover extensions to enhance Firefox for Android. '
                    u'Perform quick searches, free up system resources, take '
                    u'notes, and more.'
                )
            ),
            'experimental': StaticCategory(
                id=151,
                name=_(u'Experimental'),
                description=_(
                    u'Uncover Firefox extensions that are regularly updated '
                    u'and ready for public testing. Your feedback helps to '
                    u'guide developers to make changes in upcoming versions.'
                )
            ),
            'feeds-news-blogging': StaticCategory(
                id=147,
                name=_(u'Feeds, News, & Blogging'),
                description=_(
                    u'Stay up-to-date with Firefox extensions for news, '
                    u'web feeds, and blogs by removing clutter, utilizing '
                    u'voice readers, and more.'
                )
            ),
            'performance': StaticCategory(
                id=144,
                name=_(u'Performance'),
                description=_(
                    u'Discover extensions that give Firefox a performance '
                    u'boost. Find extensions that help you be more productive '
                    u'and efficient by blocking ads and more.'
                )
            ),
            'photos-media': StaticCategory(
                id=143,
                name=_(u'Photos & Media'),
                description=_(
                    u'Firefox extensions to enhance your experience with '
                    u'photos and media. This category includes extensions '
                    u'to reverse search images, capture full page '
                    u'screenshots, and more.'
                )
            ),
            'security-privacy': StaticCategory(
                id=149,
                name=_(u'Security & Privacy'),
                description=_(
                    u'Get Firefox extensions to surf safely and privately. '
                    u'Discover extensions that can stop sneaky ad trackers in '
                    u'their tracks, easily clear browsing history, and more.'
                )
            ),
            'shopping': StaticCategory(
                id=150,
                name=_(u'Shopping'),
                description=_(
                    u'Discover Firefox extensions that can enhance your '
                    u'online shopping experience by analyzing reviews, '
                    u'finding deals and coupons, and more.'
                )
            ),
            'social-networking': StaticCategory(
                id=148,
                name=_(u'Social Networking'),
                description=_(
                    u'Get Firefox extensions to enhance your experience on '
                    u'popular social networking websites such as YouTube, '
                    u'GitHub, Reddit, and more.'
                )
            ),
            'sports-games': StaticCategory(
                id=146,
                name=_(u'Sports & Games'),
                description=_(
                    u'Get Firefox extensions to give your entertainment '
                    u'experience a boost with live stream enhancers, sports '
                    u'updates, and more.'
                )
            ),
            'user-interface': StaticCategory(
                id=152,
                name=_(u'User Interface'),
                description=_(
                    u'Find Firefox extensions to alter web pages for easier '
                    u'reading, searching, browsing, and more.'
                )
            ),
            'other': StaticCategory(
                id=153,
                name=_(u'Other'),
                weight=333,
                description=_(
                    u'Stumble on odd and interesting extensions that can give '
                    u'Firefox for Android a boost.'
                )
            )
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
