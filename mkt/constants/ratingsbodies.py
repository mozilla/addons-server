# -*- coding: utf-8 -*-
from tower import ugettext_lazy as _lazy


class RATING(object):
    """Content rating."""


class RATING_BODY(object):
    """Content rating body."""


class DJCTQ_L(RATING):
    name = 'L'
    id = 0
    description = _lazy(u'General Audiences')


class DJCTQ_10(RATING):
    name = '10'
    id = 1
    description = _lazy(u'Not recommended for viewers younger than 10 years '
                        u'of age')


class DJCTQ_12(RATING):
    name = '12'
    id = 2
    description = _lazy(u'Not recommended for viewers younger than 12 years '
                        u'of age')


class DJCTQ_14(RATING):
    name = '14'
    id = 3
    description = _lazy(u'Not recommended for viewers younger than 14 years '
                        u'of age')


class DJCTQ_16(RATING):
    name = '16'
    id = 4
    description = _lazy(u'Not recommended for viewers younger than 16 years '
                        u'of age')


class DJCTQ_18(RATING):
    name = '18'
    id = 5
    description = _lazy(u'Not recommended for viewers younger than 18 years '
                        u'of age')


class DJCTQ(RATING_BODY):
    """
    The Brazilian game ratings body.
    """
    id = 0
    ratings = [DJCTQ_L, DJCTQ_10, DJCTQ_12, DJCTQ_14, DJCTQ_16, DJCTQ_18]
    name = 'DJCTQ'
    full_name = _lazy(u'Department of Justice, Rating, Titles and '
                      u'Qualification')
    url = ('http://portal.mj.gov.br/classificacao/data/Pages/'
           'MJ6BC270E8PTBRNN.htm')


class GENERIC_0(RATING):
    name = '0+'
    id = 0
    description = _lazy(u'General Audiences')


class GENERIC_10(RATING):
    name = '10+'
    id = 1
    description = _lazy(u'Not recommended for viewers younger than 10 years '
                        u'of age')


class GENERIC_13(RATING):
    name = '13+'
    id = 2
    description = _lazy(u'Not recommended for viewers younger than 13 years '
                        u'of age')


class GENERIC(RATING_BODY):
    """
    The generic game ratings body (used in Germany, for example).
    """
    id = 1
    ratings = [GENERIC_0, GENERIC_10, GENERIC_13]
    name = 'GENERIC'
    full_name = _lazy(u'Generic')


RATINGS_BODIES = {
    DJCTQ.id: DJCTQ,
    GENERIC.id: GENERIC
}
ALL_RATINGS = []
for rb in RATINGS_BODIES.values():
    ALL_RATINGS.extend(rb.ratings)

RATINGS_BY_NAME = []
for rb in RATINGS_BODIES.values():
    for r in rb.ratings:
        RATINGS_BY_NAME.append((ALL_RATINGS.index(r),
                                '%s - %s' % (rb.name, r.name)))
        r.ratingsbody = rb
