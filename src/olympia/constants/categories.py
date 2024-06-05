from functools import total_ordering

from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.translation import gettext_lazy as _

from olympia.constants.base import (
    ADDON_DICT,
    ADDON_EXTENSION,
    ADDON_LPAPP,
    ADDON_SLUGS,
    ADDON_STATICTHEME,
)


@total_ordering
class StaticCategory:
    """Helper to populate `CATEGORIES` and provide some helpers.

    Note that any instance is immutable to avoid changing values
    on the globally unique instances during test runs which can lead
    to hard to debug sporadic test-failures.
    """

    def __init__(self, *, id, name=None, description=None, weight=0):
        # Avoid triggering our own __setattr__ implementation
        # to keep immutability intact but set initial values.
        object.__setattr__(self, 'id', id)
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'weight', weight)
        object.__setattr__(self, 'description', description)

    def __str__(self):
        return str(self.name)

    def __repr__(self):
        return '<{}: {}>'.format(
            self.__class__.__name__,
            force_bytes(self),
        )

    def __eq__(self, other):
        return self.__class__ == other.__class__ and self.__dict__ == other.__dict__

    def __lt__(self, other):
        return (self.weight, self.name) < (other.weight, other.name)

    def get_url_path(self):
        type = ADDON_SLUGS.get(self.type, ADDON_EXTENSION)
        return reverse(f'browse.{type}', args=[self.slug])

    def _immutable(self, *args):
        raise TypeError('%r instances are immutable' % self.__class__.__name__)

    __setattr__ = __delattr__ = _immutable
    del _immutable

    def __hash__(self):
        return self.id


# The category ids are used in AddonCategory. To add a category you can pick
# any unused id.
CATEGORIES = {
    ADDON_EXTENSION: {
        'alerts-updates': StaticCategory(
            id=72,
            name=_('Alerts & Updates'),
            description=_(
                'Download Firefox extensions that help you stay '
                'up-to-date, track tasks, improve efficiency. Find '
                'extensions that reload tabs, manage productivity, and '
                'more.'
            ),
        ),
        'appearance': StaticCategory(
            id=14,
            name=_('Appearance'),
            description=_(
                'Download extensions that modify the appearance of '
                'websites and the browser Firefox. This category '
                'includes extensions for dark themes, tab management, '
                'and more.'
            ),
        ),
        'bookmarks': StaticCategory(
            id=22,
            name=_('Bookmarks'),
            description=_(
                'Download extensions that enhance bookmarks by '
                'password-protecting them, searching for duplicates, '
                'finding broken bookmarks, and more.'
            ),
        ),
        'download-management': StaticCategory(
            id=5,
            name=_('Download Management'),
            description=_(
                'Download Firefox extensions that can help download web, '
                'music and video content. You can also find extensions '
                'to manage downloads, share files, and more.'
            ),
        ),
        'feeds-news-blogging': StaticCategory(
            id=1,
            name=_('Feeds, News & Blogging'),
            description=_(
                'Download Firefox extensions that remove clutter so you '
                'can stay up-to-date on social media, catch up on blogs, '
                'RSS feeds, reduce eye strain, and more.'
            ),
        ),
        'games-entertainment': StaticCategory(
            id=142,
            name=_('Games & Entertainment'),
            description=_(
                'Download Firefox extensions to boost your entertainment '
                'experience. This category includes extensions that can '
                'enhance gaming, control video playback, and more.'
            ),
        ),
        'language-support': StaticCategory(
            id=37,
            name=_('Language Support'),
            description=_(
                'Download Firefox extensions that offer language support '
                'like grammar check, look-up words, translate text, '
                'provide text-to-speech, and more.'
            ),
        ),
        'photos-music-videos': StaticCategory(
            id=38,
            name=_('Photos, Music & Videos'),
            description=_(
                'Download Firefox extensions that enhance photo, music '
                'and video experiences. Extensions in this category '
                'modify audio and video, reverse image search, and more.'
            ),
        ),
        'privacy-security': StaticCategory(
            id=12,
            name=_('Privacy & Security'),
            description=_(
                'Download Firefox extensions to browse privately and '
                'securely. This category includes extensions to block '
                'annoying ads, prevent tracking, manage redirects, and '
                'more.'
            ),
        ),
        'search-tools': StaticCategory(
            id=13,
            name=_('Search Tools'),
            description=_(
                'Download Firefox extensions for search and look-up. '
                'This category includes extensions that highlight and '
                'search text, lookup IP addresses/domains, and more.'
            ),
        ),
        'shopping': StaticCategory(
            id=141,
            name=_('Shopping'),
            description=_(
                'Download Firefox extensions that can enhance your '
                'online shopping experience with coupon finders, deal '
                'finders, review analyzers, more.'
            ),
        ),
        'social-communication': StaticCategory(
            id=71,
            name=_('Social & Communication'),
            description=_(
                'Download Firefox extensions to enhance social media and '
                'instant messaging. This category includes improved tab '
                'notifications, video downloaders, and more.'
            ),
        ),
        'tabs': StaticCategory(
            id=93,
            name=_('Tabs'),
            description=_(
                'Download Firefox extension to customize tabs and the '
                'new tab page. Discover extensions that can control '
                'tabs, change the way you interact with them, and more.'
            ),
        ),
        'web-development': StaticCategory(
            id=4,
            name=_('Web Development'),
            description=_(
                'Download Firefox extensions that feature web '
                'development tools. This category includes extensions '
                'for GitHub, user agent switching, cookie management, '
                'and more.'
            ),
        ),
        'other': StaticCategory(
            id=73,
            name=_('Other'),
            weight=333,
            description=_(
                'Download Firefox extensions that can be unpredictable '
                'and creative, yet useful for those odd tasks.'
            ),
        ),
    },
    ADDON_STATICTHEME: {
        'abstract': StaticCategory(
            id=300,
            name=_('Abstract'),
            description=_(
                'Download Firefox artistic and conceptual themes. This '
                'category includes colorful palettes and shapes, fantasy '
                'landscapes, playful cats, psychedelic flowers.'
            ),
        ),
        'causes': StaticCategory(
            id=320,
            name=_('Causes'),
            description=_(
                'Download Firefox themes for niche interests and topics. '
                'This category includes sports themes, holidays, '
                'philanthropic causes, nationalities, and much more.'
            ),
        ),
        'fashion': StaticCategory(
            id=324,
            name=_('Fashion'),
            description=_(
                'Download Firefox themes that celebrate style of all '
                'forms—patterns, florals, textures, models, and more.'
            ),
        ),
        'film-and-tv': StaticCategory(
            id=326,
            name=_('Film and TV'),
            description=_(
                'Download Firefox themes with movies and television. '
                'This category includes anime like Uchiha Madara, movies '
                'like The Matrix, shows (Game of Thrones), and more.'
            ),
        ),
        'firefox': StaticCategory(
            id=308,
            name=_('Firefox'),
            description=_(
                'Download Firefox themes with the Firefox browser theme. '
                'This category includes colorful, diverse depictions of '
                'the Firefox logo, including more general fox themes.'
            ),
        ),
        'foxkeh': StaticCategory(
            id=310,
            name=_('Foxkeh'),
            description=_(
                'Download Firefox themes with the Japanese Firefox. This '
                'category includes themes that depict the cute Foxkeh '
                'mascot in various poses on diverse landscapes.'
            ),
        ),
        'holiday': StaticCategory(
            id=328,
            name=_('Holiday'),
            description=_(
                'Download Firefox themes with holidays. This category '
                'includes Christmas, Halloween, Thanksgiving, St. '
                'Patrick’s Day, Easter, Fourth of July, and more.'
            ),
        ),
        'music': StaticCategory(
            id=322,
            name=_('Music'),
            description=_(
                'Download Firefox themes for musical interests and '
                'artists. This category includes popular bands like '
                'Nirvana and BTS, instruments, music videos, and much '
                'more.'
            ),
        ),
        'nature': StaticCategory(
            id=302,
            name=_('Nature'),
            description=_(
                'Download Firefox themes with animals and natural '
                'landscapes. This category includes flowers, sunsets, '
                'foxes, seasons, planets, kittens, birds, and more.'
            ),
        ),
        'other': StaticCategory(
            id=314,
            name=_('Other'),
            weight=333,
            description=_(
                'Download Firefox themes that are interesting, creative, and unique.'
            ),
        ),
        'scenery': StaticCategory(
            id=306,
            name=_('Scenery'),
            description=_(
                'Download Firefox themes that feature the environment '
                'and the natural world. This category includes sunsets, '
                'beaches, illustrations, city skylines, and more.'
            ),
        ),
        'seasonal': StaticCategory(
            id=312,
            name=_('Seasonal'),
            description=_(
                'Download Firefox themes for all four seasons—fall, '
                'winter, spring, and summer. Autumn leaves, snowy '
                'mountain peaks, sunny summer days, and spring flowers.'
            ),
        ),
        'solid': StaticCategory(
            id=318,
            name=_('Solid'),
            description=_(
                'Download Firefox themes with solid and gradient colors '
                'to personalize your browser. This category includes '
                'bold reds, pastels, soft greys, and much more.'
            ),
        ),
        'sports': StaticCategory(
            id=304,
            name=_('Sports'),
            description=_(
                'Download Firefox themes that feature a variety of '
                'sports. This category includes country flags, sports '
                'teams, soccer, hockey, and more.'
            ),
        ),
        'websites': StaticCategory(
            id=316,
            name=_('Websites'),
            description=_(
                'Download Firefox themes that capture the essence of the '
                'web—captivating, unusual, and distinctive.'
            ),
        ),
    },
    ADDON_DICT: {'general': StaticCategory(id=95, name=_('General'))},
    ADDON_LPAPP: {'general': StaticCategory(id=98, name=_('General'))},
}

for type_ in CATEGORIES:
    for slug, cat in CATEGORIES[type_].items():
        # Flatten some values and set them, avoiding immutability
        # of `StaticCategory` by calling `object.__setattr__` directly.
        object.__setattr__(cat, 'slug', slug)
        object.__setattr__(cat, 'type', type_)
        object.__setattr__(cat, 'misc', slug in ('miscellaneous', 'other'))


CATEGORIES_BY_ID = {}

for type_ in CATEGORIES:
    for cat in CATEGORIES[type_].values():
        CATEGORIES_BY_ID[cat.id] = cat
