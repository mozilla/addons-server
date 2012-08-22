# -*- coding: utf-8 -*-
from tower import ugettext_lazy as _lazy


class DJCTQ_L(object):
    name = 'L'
    id = 0
    description = _lazy(u'General Audiences')


class DJCTQ_10(object):
    name = '10'
    id = 1
    description = _lazy(u'Not recommended for viewers younger than 10 years '
                        u'of age')


class DJCTQ_12(object):
    name = '12'
    id = 2
    description = _lazy(u'Not recommended for viewers younger than 12 years '
                        u'of age')


class DJCTQ_14(object):
    name = '14'
    id = 3
    description = _lazy(u'Not recommended for viewers younger than 14 years '
                        u'of age')


class DJCTQ_16(object):
    name = '16'
    id = 4
    description = _lazy(u'Not recommended for viewers younger than 16 years '
                        u'of age')


class DJCTQ_18(object):
    name = '18'
    id = 5
    description = _lazy(u'Not recommended for viewers younger than 18 years '
                        u'of age')


class DJCTQ(object):
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


RATINGS_BODIES = {
    DJCTQ.id: DJCTQ,
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
