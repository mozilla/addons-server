
class DJCTQ_L(object):
    name = 'L'
    id = 0


class DJCTQ_10(object):
    name = '10'
    id = 1


class DJCTQ_12(object):
    name = '12'
    id = 2


class DJCTQ_14(object):
    name = '14'
    id = 3


class DJCTQ_16(object):
    name = '16'
    id = 4


class DJCTQ_18(object):
    name = '18'
    id = 5


class DJCTQ(object):
    """
    The Brazilian game ratings body.
    """
    id = 0
    ratings = [DJCTQ_L, DJCTQ_10, DJCTQ_12, DJCTQ_14, DJCTQ_16, DJCTQ_18]
    name = 'DJCTQ'


RATINGS_BODIES = {
    DJCTQ.id: DJCTQ,
}
ALL_RATINGS = []
for rb in RATINGS_BODIES.values():
    ALL_RATINGS.extend(rb.ratings)

RATINGS_BY_NAME = []
for rb in RATINGS_BODIES.values():
    for r in rb.ratings:
        RATINGS_BY_NAME.append((ALL_RATINGS.index(r), '%s - %s' % (rb.name, r.name)))
        r.ratingsbody = rb
