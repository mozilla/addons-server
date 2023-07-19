from dataclasses import dataclass, field

from django.utils.translation import gettext_lazy as _

from olympia.constants import applications


@dataclass
class PromotedClass:
    id: int = None
    name: str = None
    api_name: str = None
    search_ranking_bump: float = 0.0
    warning: bool = (
        True  # See EXCLUDE_WARNING_CATEGORIES in frontend: there's no effect here
    )
    listed_pre_review: bool = False
    unlisted_pre_review: bool = False
    admin_review: bool = False
    badged: bool = False  # See BADGE_CATEGORIES in frontend too: both need changing
    autograph_signing_states: dict = field(default_factory=dict)
    can_primary_hero: bool = False
    immediate_approval: bool = False
    flag_for_human_review: bool = False

    def __bool__(self):
        return bool(self.id)


NOT_PROMOTED = PromotedClass(id=0, name=_('Not Promoted'), api_name='not_promoted')


RECOMMENDED = PromotedClass(
    id=1,
    name=_('Recommended'),
    api_name='recommended',
    search_ranking_bump=5.0,
    warning=False,
    listed_pre_review=True,
    badged=True,
    autograph_signing_states=(
        {
            applications.FIREFOX.short: 'recommended',
            applications.ANDROID.short: 'recommended-android',
        },
    ),
    can_primary_hero=True,
)


SPONSORED = PromotedClass(
    id=2,
    name=_('Sponsored'),
    api_name='sponsored',
    warning=False,
    listed_pre_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'verified',
        applications.ANDROID.short: 'verified',
    },
    can_primary_hero=True,
)


VERIFIED = PromotedClass(
    id=3,
    name=_('Verified'),
    api_name='verified',
    warning=False,
    listed_pre_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'verified',
        applications.ANDROID.short: 'verified',
    },
)


LINE = PromotedClass(
    id=4,
    name=_('By Firefox'),
    api_name='line',
    search_ranking_bump=5.0,
    warning=False,
    listed_pre_review=True,
    admin_review=True,
    badged=True,
    autograph_signing_states=(
        {
            applications.FIREFOX.short: 'line',
            applications.ANDROID.short: 'line',
        },
    ),
    can_primary_hero=True,
)


SPOTLIGHT = PromotedClass(
    id=5,
    name=_('Spotlight'),
    api_name='spotlight',
    warning=False,
    listed_pre_review=True,
    admin_review=True,
    can_primary_hero=True,
    immediate_approval=True,
)


STRATEGIC = PromotedClass(
    id=6,
    name=_('Strategic'),
    api_name='strategic',
    admin_review=True,
)


NOTABLE = PromotedClass(
    id=7,
    name=_('Notable'),
    api_name='notable',
    warning=False,
    listed_pre_review=False,
    unlisted_pre_review=False,
    flag_for_human_review=True,
)


PROMOTED_GROUPS = [
    NOT_PROMOTED,
    RECOMMENDED,
    SPONSORED,
    VERIFIED,
    LINE,
    SPOTLIGHT,
    STRATEGIC,
    NOTABLE,
]

BADGED_GROUPS = [group for group in PROMOTED_GROUPS if group.badged]
BADGED_API_NAME = 'badged'  # Special alias for all badged groups

PROMOTED_GROUPS_BY_ID = {p.id: p for p in PROMOTED_GROUPS}
PROMOTED_API_NAME_TO_IDS = {
    # we can replace this ugly syntax with dict | in 3.9 - see pep-0584
    **{p.api_name: [p.id] for p in PROMOTED_GROUPS if p},
    **{BADGED_API_NAME: list({p.id for p in BADGED_GROUPS})},
}
