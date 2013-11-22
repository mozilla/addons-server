# -*- coding: utf-8 -*-
from tower import ugettext_lazy as _lazy


DESC_GENERAL = _lazy(u'General Audiences')
# L10n: %d is the age in years.
DESC_LAZY = _lazy(u'Not recommended for users younger than %d years of age')
DESC_REJECTED = _lazy(u'Rejected for All Audiences')

NAME_GENERAL = _lazy('For all ages')
# L10n: %d is the age in years. For ages %d and higher.
NAME_LAZY = _lazy('For ages %d+')  # Fill this in after accessing.
NAME_REJECTED = _lazy(u'Rating Rejected')


class RATING(object):
    """
    Content rating.

    iarc_name -- how IARC names the rating, to talk with IARC.
    age -- minimum age of the rating's age recommendation.
    name -- how we name the rating, for translated display on all pages.
    label -- for CSS classes, to create icons.
    description -- for general translated display on consumer pages.
    """
    age = None
    name = None
    label = None
    description = None
    adult = False


class RATING_BODY(object):
    """
    Content rating body.

    iarc_name -- how IARC names the ratings body, to talk with IARC.
    ratings -- list of RATINGs associated with this body.

    name -- for general translated display on all pages.
    label -- for CSS classes, to create icons.
    description -- for general translated display on all pages.
    full_name -- in case we ever want to display the full translated name.
    url -- in case we ever want to link to the ratings body page for more info.
    """
    label = None


class CLASSIND_L(RATING):
    id = 0
    age = 0
    iarc_name = '0+'


class CLASSIND_10(RATING):
    id = 1
    age = 10
    iarc_name = '10+'


class CLASSIND_12(RATING):
    id = 2
    age = 12
    iarc_name = '12+'


class CLASSIND_14(RATING):
    id = 3
    age = 14
    iarc_name = '14+'


class CLASSIND_16(RATING):
    id = 4
    age = 16
    iarc_name = '16+'


class CLASSIND_18(RATING):
    id = 5
    age = 18
    iarc_name = '18+'
    adult = True


class CLASSIND(RATING_BODY):
    """
    The Brazilian game ratings body (aka. DEJUS, DJCTQ).
    """
    id = 0
    iarc_name = 'CLASSIND'
    ratings = (CLASSIND_L, CLASSIND_10, CLASSIND_12, CLASSIND_14, CLASSIND_16,
               CLASSIND_18)

    name = 'CLASSIND'
    description = _lazy(u'Brazil')
    full_name = _lazy(u'Department of Justice, Rating, Titles and '
                      u'Qualification')
    url = ('http://portal.mj.gov.br/classificacao/data/Pages/'
           'MJ6BC270E8PTBRNN.htm')


class GENERIC_3(RATING):
    id = 0
    age = 3
    iarc_name = '3+'


class GENERIC_7(RATING):
    id = 1
    age = 7
    iarc_name = '7+'


class GENERIC_12(RATING):
    id = 2
    age = 12
    iarc_name = '12+'


class GENERIC_16(RATING):
    id = 3
    age = 16
    iarc_name = '16+'


class GENERIC_18(RATING):
    id = 4
    age = 18
    iarc_name = '18+'
    adult = True


class GENERIC(RATING_BODY):
    """
    The generic game ratings body (used in Germany, for example).
    """
    id = 1
    iarc_name = 'Generic'
    ratings = (GENERIC_3, GENERIC_7, GENERIC_12, GENERIC_16, GENERIC_18)

    name = _lazy('Generic')
    description = ''  # No comment.
    full_name = _lazy(u'Generic')


class USK_0(RATING):
    id = 0
    age = 0
    iarc_name = '0+'


class USK_6(RATING):
    id = 1
    age = 6
    iarc_name = '6+'


class USK_12(RATING):
    id = 2
    age = 12
    iarc_name = '12+'


class USK_16(RATING):
    id = 3
    age = 16
    iarc_name = '16+'


class USK_18(RATING):
    id = 4
    age = 18
    iarc_name = '18+'
    adult = True


class USK_REJECTED(RATING):
    id = 5
    iarc_name = 'Rating Rejected'
    name = NAME_REJECTED
    description = DESC_REJECTED


class USK(RATING_BODY):
    """
    The organization responsible for game ratings in Germany
    (aka. Unterhaltungssoftware Selbstkontrolle).
    """
    id = 2
    iarc_name = 'USK'
    ratings = (USK_0, USK_6, USK_12, USK_16, USK_18, USK_REJECTED)

    name = 'USK'
    description = _lazy(u'Germany')
    full_name = _lazy(u'Entertainment Software Self-Regulation Body')
    url = 'http://www.usk.de/en/'


class ESRB_E(RATING):
    """Everybody."""
    id = 0
    age = 0
    iarc_name = 'Everyone'
    name = _lazy('Everyone')
    description = DESC_GENERAL


class ESRB_10(RATING):
    id = 1
    age = 10
    iarc_name = 'Everyone 10+'
    name = _lazy('Everyone 10+')  # L10n: `10+` is age ten and over.


class ESRB_T(RATING):
    id = 2
    age = 13
    iarc_name = 'Teen'
    name = _lazy('Teen')


class ESRB_M(RATING):
    id = 3
    age = 17
    iarc_name = 'Mature 17+'
    name = _lazy('Mature 17+')  # L10n: `17+` is age seventeen and over.


class ESRB_A(RATING):
    id = 4
    age = 18
    iarc_name = 'Adults Only'
    name = _lazy('Adults Only 18+')  # L10n: `18+` is age eighteen and over.
    adult = True


class ESRB_RP(RATING):
    id = 4
    iarc_name = 'Rating Pending'
    label = 'pending'
    name = _lazy('Rating Pending')


class ESRB(RATING_BODY):
    """
    The North American game ratings body (i.e. USA, Canada).
    """
    id = 3
    iarc_name = 'ESRB'
    ratings = (ESRB_E, ESRB_10, ESRB_T, ESRB_M, ESRB_A)

    name = 'ESRB'
    description = _lazy(u'N. America')  # L10n: `N.` stands for North.
    full_name = _lazy(u'Entertainment Software Rating Board')
    url = 'http://esrb.org'


class PEGI_3(RATING):
    id = 0
    age = 3
    iarc_name = '3+'


class PEGI_7(RATING):
    id = 1
    age = 7
    iarc_name = '7+'


class PEGI_12(RATING):
    id = 2
    age = 12
    iarc_name = '12+'


class PEGI_16(RATING):
    id = 3
    age = 16
    iarc_name = '16+'


class PEGI_18(RATING):
    id = 4
    age = 18
    iarc_name = '18+'
    adult = True


class PEGI(RATING_BODY):
    """
    The European game ratings body (i.e. UK, Poland, Spain).
    """
    id = 4
    iarc_name = 'PEGI'
    ratings = (PEGI_3, PEGI_7, PEGI_12, PEGI_16, PEGI_18)

    name = 'PEGI'
    description = _lazy(u'Europe')
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


ALL_RATINGS_BODIES = [CLASSIND, GENERIC, USK, ESRB, PEGI]


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
                    (all_ratings.index(r),
                     u'%s - %s' % (rb.name, dehydrate_rating(r).name)))
    return ratings_choices


def dehydrate_rating(rating):
    """
    Returns a rating with translated fields attached and with fields that are
    easily created dynamically.
    """
    if rating.label is None:
        rating.label = str(rating.age)
    if rating.name is None:
        if rating.age == 0:
            rating.name = unicode(NAME_GENERAL)
        else:
            rating.name = unicode(NAME_LAZY) % rating.age
    if rating.description is None:
        if rating.age == 0:
            rating.description = unicode(DESC_GENERAL)
        else:
            rating.description = unicode(DESC_LAZY) % rating.age

    rating.name = unicode(rating.name)
    rating.description = unicode(rating.description)
    return rating


def dehydrate_ratings_body(body):
    """Returns a rating body with translated fields attached."""
    if body.label is None:
        body.label = body.iarc_name.lower().replace(' ', '-')

    body.name = unicode(body.name)
    body.description = unicode(body.description)
    return body
