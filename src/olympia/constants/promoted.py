from collections import namedtuple

from django.utils.translation import ugettext_lazy as _


_PromotedSuperClass = namedtuple(
    '_PromotedSuperClass', [
        'id',
        'name',
        'api_name',
        'search_ranking_bump',
        'warning',
        'pre_review',
        'admin_review'
    ],
    defaults=(
        0,  # search_ranking_bump
        True,  # warning
        False,  # pre_review
        False,  # admin_review
    )
)


class PromotedClass(_PromotedSuperClass):
    __slots__ = ()

    def __bool__(self):
        return bool(self.id)


NOT_PROMOTED = PromotedClass(
    id=0,
    name=_('Not Promoted'),
    api_name='not_promoted',
)

RECOMMENDED = PromotedClass(
    id=1,
    name=_('Recommended'),
    api_name='recommended',
    search_ranking_bump=1000,  # TODO: confirm this bump
    warning=False,
    pre_review=True,
)

VERIFIED_ONE = PromotedClass(
    id=2,
    name=_('Verified - Tier 1'),
    api_name='sponsored',
    search_ranking_bump=500,  # TODO: confirm this bump
    warning=False,
    pre_review=True,
    admin_review=True,
)

VERIFIED_TWO = PromotedClass(
    id=3,
    name=_('Verified - Tier 2'),
    api_name='verified',
    warning=False,
    pre_review=True,
)

LINE = PromotedClass(
    id=4,
    name=_('Line'),
    api_name='line',
    warning=False,
    pre_review=True,
    admin_review=True,
)

SPOTLIGHT = PromotedClass(
    id=5,
    name=_('Spotlight'),
    api_name='spotlight',
    warning=False,
    pre_review=True,
    admin_review=True,
)

STRATEGIC = PromotedClass(
    id=6,
    name=_('Strategic'),
    api_name='strategic',
    admin_review=True,
)

PROMOTED_GROUPS = [
    NOT_PROMOTED,
    RECOMMENDED,
    VERIFIED_ONE,
    VERIFIED_TWO,
    LINE,
    SPOTLIGHT,
    STRATEGIC,
]

PRE_REVIEW_GROUPS = [group for group in PROMOTED_GROUPS if group.pre_review]

PROMOTED_GROUPS_BY_ID = {p.id: p for p in PROMOTED_GROUPS}
