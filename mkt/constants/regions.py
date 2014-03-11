import inspect
import sys

from tower import ugettext_lazy as _lazy

from mkt.constants import ratingsbodies
from mkt.constants.ratingsbodies import slugify_iarc_name


class REGION(object):
    """
    A region is like a country but more confusing.

    id::
        The primary key used to identify a region in the DB.

    name::
        The text that appears in the header and region selector menu.

    slug::
        The text that gets stored in the cookie or in ?region=<slug>.
        Use the ISO-3166 code please.

    mcc::
        Don't know what an ITU MCC is? They're useful for carrier billing.
        Read http://en.wikipedia.org/wiki/List_of_mobile_country_codes

    adolescent::
        With a mature region (meaning, it has a volume of useful data) we
        are able to calculate ratings and rankings independently. If a
        store is immature it will continue using the global popularity
        measure. If a store is mature it will use the smaller, more
        relevant set of data.

    weight::
        Determines sort order (after slug).

    special::
        Does this region need to be reviewed separately? That region is
        special.

    """
    id = None
    name = slug = ''
    default_currency = 'USD'
    default_language = 'en-US'
    adolescent = True
    mcc = None
    weight = 0
    ratingsbody = None
    special = False


class RESTOFWORLD(REGION):
    id = 1
    name = _lazy(u'Rest of World')
    slug = 'restofworld'
    weight = -1


class US(REGION):
    id = 2
    name = _lazy(u'United States')
    slug = 'us'
    mcc = 310
    weight = 1
    ratingsbody = ratingsbodies.ESRB


class UK(REGION):
    id = 4
    name = _lazy(u'United Kingdom')
    slug = 'uk'
    default_currency = 'GBP'
    mcc = 235
    ratingsbody = ratingsbodies.PEGI


class BR(REGION):
    id = 7
    name = _lazy(u'Brazil')
    slug = 'br'
    default_currency = 'BRL'
    default_language = 'pt-BR'
    mcc = 724
    ratingsbody = ratingsbodies.CLASSIND


class SPAIN(REGION):
    id = 8
    name = _lazy(u'Spain')
    slug = 'es'
    default_currency = 'EUR'
    default_language = 'es'
    mcc = 214
    ratingsbody = ratingsbodies.PEGI


class CO(REGION):
    id = 9
    name = _lazy(u'Colombia')
    slug = 'co'
    default_currency = 'COP'
    default_language = 'es'
    mcc = 732
    ratingsbody = ratingsbodies.ESRB


class VE(REGION):
    id = 10
    name = _lazy(u'Venezuela')
    slug = 've'
    default_currency = 'USD'
    default_language = 'es'
    mcc = 734
    ratingsbody = ratingsbodies.ESRB


class PL(REGION):
    id = 11
    name = _lazy(u'Poland')
    slug = 'pl'
    default_currency = 'PLN'
    default_language = 'pl'
    mcc = 260
    ratingsbody = ratingsbodies.PEGI


class MX(REGION):
    id = 12
    name = _lazy(u'Mexico')
    slug = 'mx'
    default_currency = 'MXN'
    default_language = 'es'
    mcc = 334
    ratingsbody = ratingsbodies.ESRB


class HU(REGION):
    id = 13
    name = _lazy(u'Hungary')
    slug = 'hu'
    default_currency = 'HUF'
    default_language = 'hu'
    mcc = 216
    ratingsbody = ratingsbodies.PEGI


class DE(REGION):
    id = 14
    name = _lazy(u'Germany')
    slug = 'de'
    default_currency = 'EUR'
    default_language = 'de'
    mcc = 262
    ratingsbody = ratingsbodies.USK


class ME(REGION):
    id = 15
    name = _lazy(u'Montenegro')
    slug = 'me'
    default_currency = 'EUR'
    default_language = 'srp'
    mcc = 297


class RS(REGION):
    id = 16
    name = _lazy(u'Serbia')
    slug = 'rs'
    default_currency = 'RSD'
    default_language = 'sr'
    mcc = 220


class GR(REGION):
    id = 17
    name = _lazy(u'Greece')
    slug = 'gr'
    default_currency = 'EUR'
    default_language = 'el'
    mcc = 202
    ratingsbody = ratingsbodies.PEGI


class PE(REGION):
    id = 18
    name = _lazy(u'Peru')
    slug = 'pe'
    default_currency = 'PEN'
    default_language = 'es'
    mcc = 716
    ratingsbody = ratingsbodies.ESRB


class UY(REGION):
    id = 19
    name = _lazy(u'Uruguay')
    slug = 'uy'
    default_currency = 'UYU'
    default_language = 'es'
    mcc = 748
    ratingsbody = ratingsbodies.ESRB


class AR(REGION):
    id = 20
    name = _lazy(u'Argentina')
    slug = 'ar'
    default_currency = 'ARS'
    default_language = 'es'
    mcc = 722
    ratingsbody = ratingsbodies.ESRB


class CN(REGION):
    id = 21
    name = _lazy(u'China')
    slug = 'cn'
    default_currency = 'RMB'
    default_language = 'zh-CN'
    mcc = 460
    special = True


class IT(REGION):
    id = 22
    name = _lazy(u'Italy')
    slug = 'it'
    default_currency = 'EUR'
    default_language = 'it'
    mcc = 222
    ratingsbody = ratingsbodies.PEGI


class CL(REGION):
    id = 23
    name = _lazy(u'Chile')
    slug = 'cl'
    default_currency = 'CLP'
    default_language = 'es'
    mcc = 730
    ratingsbody = ratingsbodies.ESRB


# Create a list of tuples like so (in alphabetical order):
#
#     [('restofworld', <class 'mkt.constants.regions.RESTOFWORLD'>),
#      ('brazil', <class 'mkt.constants.regions.BR'>),
#      ('usa', <class 'mkt.constants.regions.US'>)]
#

DEFINED = sorted(inspect.getmembers(sys.modules[__name__], inspect.isclass),
                 key=lambda x: getattr(x, 'slug', None))
REGIONS_CHOICES = (
    [('restofworld', RESTOFWORLD)] +
    sorted([(v.slug, v) for k, v in DEFINED if v.id and v.weight > -1],
           key=lambda x: x[1].weight, reverse=True)
)

BY_SLUG = sorted([v for k, v in DEFINED if v.id and v.weight > -1],
                 key=lambda v: v.slug)

REGIONS_CHOICES_SLUG = ([('restofworld', RESTOFWORLD)] +
                        [(v.slug, v) for v in BY_SLUG])
REGIONS_CHOICES_ID = ([(RESTOFWORLD.id, RESTOFWORLD)] +
                      [(v.id, v) for v in BY_SLUG])
# Rest of World last here so we can display it after all the other regions.
REGIONS_CHOICES_NAME = ([(v.id, v.name) for v in BY_SLUG] +
                        [(RESTOFWORLD.id, RESTOFWORLD.name)])

REGIONS_DICT = dict(REGIONS_CHOICES)
REGIONS_CHOICES_ID_DICT = dict(REGIONS_CHOICES_ID)
# Provide a dict for looking up the region by slug that includes aliases:
# - "worldwide" is an alias for RESTOFWORLD (bug 940561).
# - "gb" is an alias for UK (bug 973883).
REGION_LOOKUP = dict(REGIONS_DICT.items() +
                     [('worldwide', RESTOFWORLD), ('gb', UK)])
ALL_REGIONS = frozenset(REGIONS_DICT.values())
ALL_REGION_IDS = sorted(REGIONS_CHOICES_ID_DICT.keys())

SPECIAL_REGIONS = [x for x in BY_SLUG if x.special]
SPECIAL_REGION_IDS = sorted(x.id for x in SPECIAL_REGIONS)

# Regions not including restofworld.
REGION_IDS = sorted(REGIONS_CHOICES_ID_DICT.keys())[1:]

GENERIC_RATING_REGION_SLUG = 'generic'


def ALL_REGIONS_WITH_CONTENT_RATINGS():
    """Regions that have ratings bodies."""
    import waffle

    if waffle.switch_is_active('iarc'):
        return [x for x in ALL_REGIONS if x.ratingsbody]

    # Only require content ratings in Brazil/Germany without IARC switch.
    return [BR, DE]


def ALL_REGIONS_WITHOUT_CONTENT_RATINGS():
    """
    Regions without ratings bodies and fallback to the GENERIC rating body.
    """
    return set(ALL_REGIONS) - set(ALL_REGIONS_WITH_CONTENT_RATINGS())


def REGION_TO_RATINGS_BODY():
    """
    Return a map of region slugs to ratings body labels for use in
    serializers and to send to Fireplace.

    e.g. {'us': 'esrb', 'mx': 'esrb', 'es': 'pegi', 'br': 'classind'}.
    """
    import waffle

    # Create the mapping.
    region_to_bodies = {}
    for region in ALL_REGIONS_WITH_CONTENT_RATINGS():
        ratings_body_label = GENERIC_RATING_REGION_SLUG
        if region.ratingsbody:
            ratings_body_label = slugify_iarc_name(region.ratingsbody)
        region_to_bodies[region.slug] = ratings_body_label

    # Resolve edge cases related to switches.
    if not waffle.switch_is_active('iarc'):
        region_to_bodies.update({
            'de': GENERIC_RATING_REGION_SLUG
        })

    return region_to_bodies
