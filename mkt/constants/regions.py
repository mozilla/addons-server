import inspect
import sys

from tower import ugettext_lazy as _lazy

from mkt.constants import ratingsbodies


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


class WORLDWIDE(REGION):
    id = 1
    name = _lazy(u'Worldwide')
    slug = 'worldwide'
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


class VE(REGION):
    id = 10
    name = _lazy(u'Venezuela')
    slug = 've'
    default_currency = 'USD'
    default_language = 'es'
    mcc = 734


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
    # TODO: change to GENERIC on IARC deploy (switch_is_active('iarc')).
    # ratingsbody = ratingsbodies.USK
    ratingsbody = ratingsbodies.GENERIC


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


class UY(REGION):
    id = 19
    name = _lazy(u'Uruguay')
    slug = 'uy'
    default_currency = 'UYU'
    default_language = 'es'
    mcc = 748


class AR(REGION):
    id = 20
    name = _lazy(u'Argentina')
    slug = 'ar'
    default_currency = 'ARS'
    default_language = 'es'
    mcc = 722


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
    special = False


# Create a list of tuples like so (in alphabetical order):
#
#     [('worldwide', <class 'mkt.constants.regions.WORLDWIDE'>),
#      ('brazil', <class 'mkt.constants.regions.BR'>),
#      ('usa', <class 'mkt.constants.regions.US'>)]
#

DEFINED = sorted(inspect.getmembers(sys.modules[__name__], inspect.isclass),
                 key=lambda x: getattr(x, 'slug', None))
REGIONS_CHOICES = (
    [('worldwide', WORLDWIDE)] +
    sorted([(v.slug, v) for k, v in DEFINED if v.id and v.weight > -1],
           key=lambda x: x[1].weight, reverse=True)
)

BY_SLUG = sorted([v for k, v in DEFINED if v.id and v.weight > -1],
                 key=lambda v: v.slug)

REGIONS_CHOICES_SLUG = ([('worldwide', WORLDWIDE)] +
                        [(v.slug, v) for v in BY_SLUG])
REGIONS_CHOICES_ID = ([(WORLDWIDE.id, WORLDWIDE)] +
                      [(v.id, v) for v in BY_SLUG])
# Worldwide last here so we can display it after all the other regions.
REGIONS_CHOICES_NAME = ([(v.id, v.name) for v in BY_SLUG] +
                        [(WORLDWIDE.id, WORLDWIDE.name)])

REGIONS_DICT = dict(REGIONS_CHOICES)
REGIONS_CHOICES_ID_DICT = dict(REGIONS_CHOICES_ID)
ALL_REGIONS = frozenset(REGIONS_DICT.values())
ALL_REGION_IDS = sorted(REGIONS_CHOICES_ID_DICT.keys())

SPECIAL_REGIONS = [x for x in BY_SLUG if x.special]
SPECIAL_REGION_IDS = sorted(x.id for x in SPECIAL_REGIONS)

# Regions not including worldwide.
REGION_IDS = sorted(REGIONS_CHOICES_ID_DICT.keys())[1:]

GENERIC_RATING_REGION_SLUG = 'generic'

def ALL_REGIONS_WITH_CONTENT_RATINGS():
    """Regions that have ratings bodies."""
    import waffle

    if waffle.switch_is_active('iarc'):
        return [x for x in ALL_REGIONS if x.ratingsbody]

    # Only require content ratings in Brazil/Germany without IARC switch.
    return [BR, DE]

def ALL_REGIONS_WO_CONTENT_RATINGS():
    """
    Regions without ratings bodies and fallback to the GENERIC rating body.
    """
    return set(ALL_REGIONS) - set(ALL_REGIONS_WITH_CONTENT_RATINGS())
