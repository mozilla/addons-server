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
    """
    id = None
    name = slug = ''
    default_currency = 'USD'
    default_language = 'en-US'
    adolescent = True
    mcc = None
    weight = 0
    ratingsbodies = ()
    has_payments = False


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
    has_payments = True


class UK(REGION):
    id = 4
    name = _lazy(u'United Kingdom')
    slug = 'uk'
    default_currency = 'GBP'
    mcc = 235


class BR(REGION):
    id = 7
    name = _lazy(u'Brazil')
    slug = 'br'
    default_currency = 'BRL'
    default_language = 'pt-BR'
    mcc = 724
    ratingsbodies = (ratingsbodies.DJCTQ,)
    has_payments = True


class SPAIN(REGION):
    id = 8
    name = _lazy(u'Spain')
    slug = 'spain'
    default_currency = 'EUR'
    default_language = 'es'
    mcc = 214
    has_payments = True


# Create a list of tuples like so (in alphabetical order):
#
#     [('worldwide', <class 'mkt.constants.regions.WORLDWIDE'>),
#      ('brazil', <class 'mkt.constants.regions.BRAZIL'>),
#      ('usa', <class 'mkt.constants.regions.BRAZIL'>)]
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
REGIONS_CHOICES_NAME = ([(WORLDWIDE.id, WORLDWIDE.name)] +
                        [(v.id, v.name) for v in BY_SLUG])

REGIONS_DICT = dict(REGIONS_CHOICES)
REGIONS_CHOICES_ID_DICT = dict(REGIONS_CHOICES_ID)
ALL_REGIONS = frozenset(REGIONS_DICT.values())
ALL_PAID_REGIONS = frozenset(r for r in ALL_REGIONS if r.has_payments)

ALL_REGION_IDS = sorted(REGIONS_CHOICES_ID_DICT.keys())
ALL_PAID_REGION_IDS = sorted(r.id for r in ALL_PAID_REGIONS)
REGION_IDS = sorted(REGIONS_CHOICES_ID_DICT.keys())[1:]
