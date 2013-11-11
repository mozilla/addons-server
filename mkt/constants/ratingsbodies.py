# -*- coding: utf-8 -*-
from tower import ugettext_lazy as _lazy


DESC_GENERAL = _lazy(u'General Audiences')
DESC_3 = _lazy(u'Not recommended for users younger than 3 years of age')
DESC_6 = _lazy(u'Not recommended for users younger than 6 years of age')
DESC_7 = _lazy(u'Not recommended for users younger than 7 years of age')
DESC_10 = _lazy(u'Not recommended for users younger than 10 years of age')
DESC_12 = _lazy(u'Not recommended for users younger than 12 years of age')
DESC_13 = _lazy(u'Not recommended for users younger than 13 years of age')
DESC_14 = _lazy(u'Not recommended for users younger than 14 years of age')
DESC_16 = _lazy(u'Not recommended for users younger than 16 years of age')
DESC_17 = _lazy(u'Not recommended for users younger than 17 years of age')
DESC_18 = _lazy(u'Not recommended for users younger than 18 years of age')
DESC_REJECTED = _lazy(u'Rejected for All Audiences')

RATING_DESCS = {
    '0': DESC_GENERAL,
    '3': DESC_3,
    '6': DESC_6,
    '7': DESC_7,
    '10': DESC_10,
    '12': DESC_12,
    '13': DESC_13,
    '14': DESC_14,
    '16': DESC_16,
    '17': DESC_17,
    '18': DESC_18,
    'X': DESC_REJECTED,
}


class RATING(object):
    """Content rating."""


class RATING_BODY(object):
    """Content rating body."""


class CLASSIND_L(RATING):
    id = 0
    name = '0+'
    description = RATING_DESCS['0']


class CLASSIND_10(RATING):
    id = 1
    name = '10+'
    description = RATING_DESCS['10']


class CLASSIND_12(RATING):
    id = 2
    name = '12+'
    description = RATING_DESCS['12']


class CLASSIND_14(RATING):
    id = 3
    name = '14+'
    description = RATING_DESCS['14']


class CLASSIND_16(RATING):
    id = 4
    name = '16+'
    description = RATING_DESCS['16']


class CLASSIND_18(RATING):
    id = 5
    name = '18+'
    description = RATING_DESCS['18']


class CLASSIND(RATING_BODY):
    """
    The Brazilian game ratings body (aka. DEJUS, DJCTQ).
    """
    id = 0
    name = 'CLASSIND'
    description = _lazy(u'Brazil')

    ratings = (CLASSIND_L, CLASSIND_10, CLASSIND_12, CLASSIND_14, CLASSIND_16,
               CLASSIND_18)

    full_name = _lazy(u'Department of Justice, Rating, Titles and '
                      u'Qualification')
    url = ('http://portal.mj.gov.br/classificacao/data/Pages/'
           'MJ6BC270E8PTBRNN.htm')


class GENERIC_3(RATING):
    id = 0
    name = '3+'
    description = RATING_DESCS['3']


class GENERIC_7(RATING):
    id = 1
    name = '7+'
    description = RATING_DESCS['7']


class GENERIC_12(RATING):
    id = 2
    name = '12+'
    description = RATING_DESCS['12']


class GENERIC_16(RATING):
    id = 3
    name = '16+'
    description = RATING_DESCS['16']


class GENERIC_18(RATING):
    id = 4
    name = '18+'
    description = RATING_DESCS['18']


class GENERIC(RATING_BODY):
    """
    The generic game ratings body (used in Germany, for example).
    """
    id = 1
    name = 'Generic'
    description = ''  # No comment.

    ratings = (GENERIC_3, GENERIC_7, GENERIC_12, GENERIC_16, GENERIC_18)

    full_name = _lazy(u'Generic')


class USK_0(RATING):
    id = 0
    name = '0+'
    description = RATING_DESCS['0']


class USK_6(RATING):
    id = 1
    name = '6+'
    description = RATING_DESCS['6']


class USK_12(RATING):
    id = 2
    name = '12+'
    description = RATING_DESCS['12']


class USK_16(RATING):
    id = 3
    name = '16+'
    description = RATING_DESCS['16']


class USK_18(RATING):
    id = 4
    name = '18+'
    description = RATING_DESCS['18']


class USK_REJECTED(RATING):
    id = 5
    name = _lazy('Rejected')
    description = RATING_DESCS['X']


class USK(RATING_BODY):
    """
    The organization responsible for game ratings in Germany
    (aka. Unterhaltungssoftware Selbstkontrolle).
    """
    id = 2
    name = 'USK'
    description = _lazy(u'Germany')

    ratings = (USK_0, USK_6, USK_12, USK_16, USK_18, USK_REJECTED)

    full_name = _lazy(u'Entertainment Software Self-Regulation Body')
    url = 'http://www.usk.de/en/'


class ESRB_E(RATING):
    """Everybody."""
    id = 0
    name = _lazy('Everyone')
    slug = '0'
    description = RATING_DESCS['0']


class ESRB_10(RATING):
    id = 1
    name = _lazy('Everyone 10+')  # L10n: `10+` is age ten and over.
    slug = '10'
    description = RATING_DESCS['10']


class ESRB_T(RATING):
    id = 2
    name = _lazy('Teen')
    slug = '13'
    description = RATING_DESCS['13']


class ESRB_M(RATING):
    id = 3
    name = _lazy('Mature 17+')  # L10n: `17+` is age seventeen and over.
    slug = '17'
    description = RATING_DESCS['17']


class ESRB_A(RATING):
    id = 4
    name = _lazy('Adults Only 18+')  # L10n: `18+` is age eighteen and over.
    slug = '18'
    description = RATING_DESCS['18']


class ESRB_RP(RATING):
    id = 4
    name = _lazy('Rating Pending')
    slug = 'pending'
    description = RATING_DESCS['18']


class ESRB(RATING_BODY):
    """
    The North American game ratings body (i.e. USA, Canada).
    """
    id = 3
    name = 'ESRB'
    description = _lazy(u'N. America')  # L10n: `N.` stands for North.

    ratings = (ESRB_E, ESRB_10, ESRB_T, ESRB_M, ESRB_A)

    full_name = _lazy(u'Entertainment Software Rating Board')
    url = 'http://esrb.org'


class PEGI_3(RATING):
    id = 0
    name = '3+'
    description = RATING_DESCS['3']


class PEGI_7(RATING):
    id = 1
    name = '7+'
    description = RATING_DESCS['7']


class PEGI_12(RATING):
    id = 2
    name = '12+'
    description = RATING_DESCS['12']


class PEGI_16(RATING):
    id = 3
    name = '16+'
    description = RATING_DESCS['16']


class PEGI_18(RATING):
    id = 4
    name = '18+'
    description = RATING_DESCS['18']


class PEGI(RATING_BODY):
    """
    The European game ratings body (i.e. UK, Poland, Spain).
    """
    id = 4
    name = 'PEGI'
    description = _lazy(u'Europe')

    ratings = (PEGI_3, PEGI_7, PEGI_12, PEGI_16, PEGI_18)

    full_name = _lazy(u'Pan European Game Information')
    url = 'http://www.pegi.info'


RATINGS_BODIES = {
    CLASSIND.id: CLASSIND,
    GENERIC.id: GENERIC,
    USK.id: USK,
    ESRB.id: ESRB,
    PEGI.id: PEGI,
}


# Attach ratings bodies to ratings.
for rb in RATINGS_BODIES.values():
    for r in rb.ratings:
        r.ratingsbody = rb


def ALL_RATINGS():
    """
    List of all ratings with waffled bodies.
    """
    import waffle

    ALL_RATINGS = []
    for rb in RATINGS_BODIES.values():
        if rb in (CLASSIND, GENERIC) or waffle.switch_is_active('iarc'):
            ALL_RATINGS.extend(rb.ratings)
    return ALL_RATINGS


def RATINGS_BY_NAME():
    """
    Create a list of tuples (choices) after we know the locale since this
    attempts to concatenate two lazy translations in constants file.
    """
    import waffle

    all_ratings = ALL_RATINGS()

    ratings_choices = []
    for rb in RATINGS_BODIES.values():
        if rb in (CLASSIND, GENERIC) or waffle.switch_is_active('iarc'):
            for r in rb.ratings:
                ratings_choices.append(
                    (all_ratings.index(r), u'%s - %s' % (rb.name, r.name)))
    return ratings_choices
