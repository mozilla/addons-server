from collections import namedtuple

from django.utils.translation import ugettext_lazy as _

from olympia.constants import applications


_PromotedSuperClass = namedtuple(
    '_PromotedSuperClass',
    [
        # Be careful when adding to this list to adjust defaults too.
        'id',
        'name',
        'api_name',
        'search_ranking_bump',
        'warning',
        'pre_review',
        'admin_review',
        'badged',
        'autograph_signing_states',
        'can_primary_hero',
        'can_be_selected_by_adzerk',
        'require_subscription',
        'immediate_approval',
    ],
    defaults=(
        # "Since fields with a default value must come after any fields without
        # a default, the defaults are applied to the rightmost parameters"
        0.0,  # search_ranking_bump
        True,  # warning
        False,  # pre_review
        False,  # admin_review
        False,  # badged
        {},  # autograph_signing_states - should be a dict of App.short: state
        False,  # can_primary_hero - can be added to a primary hero shelf
        False,  # can_be_selected_by_adzerk
        False,  # require_subscription
        False,  # immediate_approval - will addon be auto-approved once added
    ),
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
    search_ranking_bump=5.0,
    warning=False,
    pre_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'recommended',
        applications.ANDROID.short: 'recommended-android',
    },
    can_primary_hero=True,
)

SPONSORED = PromotedClass(
    id=2,
    name=_('Sponsored'),
    api_name='sponsored',
    warning=False,
    pre_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'verified',
        applications.ANDROID.short: 'verified',
    },
    can_primary_hero=True,
    can_be_selected_by_adzerk=True,
    require_subscription=True,
)

VERIFIED = PromotedClass(
    id=3,
    name=_('Verified'),
    api_name='verified',
    warning=False,
    pre_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'verified',
        applications.ANDROID.short: 'verified',
    },
    can_be_selected_by_adzerk=True,
    require_subscription=True,
)

LINE = PromotedClass(
    id=4,
    name=_('By Firefox'),
    api_name='line',
    search_ranking_bump=5.0,
    warning=False,
    pre_review=True,
    admin_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'line',
        applications.ANDROID.short: 'line',
    },
    can_primary_hero=True,
    can_be_selected_by_adzerk=True,
)

SPOTLIGHT = PromotedClass(
    id=5,
    name=_('Spotlight'),
    api_name='spotlight',
    warning=False,
    pre_review=True,
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

PROMOTED_GROUPS = [
    NOT_PROMOTED,
    RECOMMENDED,
    SPONSORED,
    VERIFIED,
    LINE,
    SPOTLIGHT,
    STRATEGIC,
]

PRE_REVIEW_GROUPS = [group for group in PROMOTED_GROUPS if group.pre_review]
BADGED_GROUPS = [group for group in PROMOTED_GROUPS if group.badged]
BADGED_API_NAME = 'badged'  # Special alias for all badged groups

PROMOTED_GROUPS_BY_ID = {p.id: p for p in PROMOTED_GROUPS}
PROMOTED_API_NAME_TO_IDS = {
    # we can replace this ugly syntax with dict | in 3.9 - see pep-0584
    **{p.api_name: [p.id] for p in PROMOTED_GROUPS if p},
    **{BADGED_API_NAME: list({p.id for p in BADGED_GROUPS})},
}

BILLING_PERIOD_MONTHLY = 'monthly'
BILLING_PERIOD_YEARLY = 'yearly'
BILLING_PERIODS = (
    (BILLING_PERIOD_MONTHLY, 'Monthly'),
    (BILLING_PERIOD_YEARLY, 'Yearly'),
)
