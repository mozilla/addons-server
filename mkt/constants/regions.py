# Don't know what an ITU MCC is? We'll be using the for carrier billing.
# Read http://en.wikipedia.org/wiki/List_of_mobile_country_codes

import inspect
import sys

from tower import ugettext_lazy as _lazy


class REGION(object):
    """A region is like a country but more confusing."""
    id = None
    name = None
    default_currency = 'USD'
    default_language = 'en-US'
    adolescent = True
    mcc = None  # See comment above.


class WORLDWIDE(REGION):
    id = 1
    name = _lazy(u'Worldwide')


class USA(REGION):
    id = 2
    name = _lazy(u'United States')
    mcc = 310


class BRAZIL(REGION):
    id = 3
    name = _lazy(u'Brazil')
    default_currency = 'BRL'
    default_language = 'pt-BR'
    mcc = 724


# Create a list of tuples like so:
#
#     [('WORLWIDE', <class 'mkt.constants.regions.WORLWIDE'>),
#      ('BRAZIL', <class 'mkt.constants.regions.BRAZIL'>),
#      ...]
#
REGIONS_CHOICES = sorted(inspect.getmembers(sys.modules[__name__],
                                            inspect.isclass),
                         key=lambda x: x[1].id)
REGIONS_DICT = dict(REGIONS_CHOICES)
