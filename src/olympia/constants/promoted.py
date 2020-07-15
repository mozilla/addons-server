from django.utils.translation import ugettext_lazy as _


class PromotedClass():
    id = 0
    name = 'Not Promoted'
    search_ranking_bump = 0
    warning = True
    pre_review = False
    admin_review = False


class NOT_PROMOTED(PromotedClass):
    pass


class RECOMMENDED(PromotedClass):
    id = 1
    name = _('Recommended')
    search_ranking_bump = 1000  # TODO: confirm this bump
    warning = False
    pre_review = True


class VERIFIED_ONE(PromotedClass):
    id = 2
    name = _('Verified - Tier 1')
    search_ranking_bump = 500  # TODO: confirm this bump
    warning = False
    pre_review = True
    admin_review = True


class VERIFIED_TWO(PromotedClass):
    id = 3
    name = _('Verified - Tier 2')
    warning = False
    pre_review = True


class LINE(PromotedClass):
    id = 4
    name = _('Line')
    warning = False
    pre_review = True
    admin_review = True


class SPOTLIGHT(PromotedClass):
    id = 5
    name = _('Spotlight')
    warning = False
    pre_review = True
    admin_review = True


class STRATEGIC(PromotedClass):
    id = 6
    name = _('Strategic')
    admin_review = True


PROMOTED_GROUPS = [
    NOT_PROMOTED,
    RECOMMENDED,
    VERIFIED_ONE,
    VERIFIED_TWO,
    LINE,
    SPOTLIGHT,
    STRATEGIC,
]

PROMOTED_GROUPS_BY_ID = {p.id: p for p in PROMOTED_GROUPS}
