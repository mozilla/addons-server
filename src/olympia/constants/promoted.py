from collections import namedtuple

from django.utils.translation import gettext_lazy as _

from olympia.constants import applications


_PromotedSuperClass = namedtuple(
    '_PromotedSuperClass',
    [
        # Be careful when adding to this list to adjust defaults too.
        'id',
        'name',
        'api_name',
        'search_ranking_bump',
        'listed_pre_review',
        'unlisted_pre_review',
        'admin_review',
        'badged',  # See BADGE_CATEGORIES in frontend too: both need changing
        'autograph_signing_states',
        'can_primary_hero',  # can be added to a primary hero shelf
        'immediate_approval',  # will addon be auto-approved once added
        'flag_for_human_review',  # will be add-on be flagged for another review
        'can_be_compatible_with_all_fenix_versions',  # If addon is promoted for Android
        'high_profile',  # the add-on is considered high-profile for review purposes
        'high_profile_rating',  # developer replies are considered high-profile
    ],
    defaults=(
        # "Since fields with a default value must come after any fields without
        # a default, the defaults are applied to the rightmost parameters"
        # No defaults for: id, name, api_name.
        0.0,  # search_ranking_bump
        False,  # listed_pre_review
        False,  # unlisted_pre_review
        False,  # admin_review
        False,  # badged
        {},  # autograph_signing_states - should be a dict of App.short: state
        False,  # can_primary_hero
        False,  # immediate_approval
        False,  # flag_for_human_review
        False,  # can_be_compatible_with_all_fenix_versions
        False,  # high_profile
        False,  # high_profile_rating
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
    listed_pre_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'recommended',
        applications.ANDROID.short: 'recommended-android',
    },
    can_primary_hero=True,
    can_be_compatible_with_all_fenix_versions=True,
    high_profile=True,
    high_profile_rating=True,
)

# Obsolete, never used in production, only there to prevent us from re-using
# the ids. Both these classes used to have specific properties set that were
# removed since they are not supposed to be used anyway.
_SPONSORED = PromotedClass(id=2, name='Sponsored', api_name='sponsored')
_VERIFIED = PromotedClass(id=3, name='Verified', api_name='verified')

LINE = PromotedClass(
    id=4,
    name=_('By Firefox'),
    api_name='line',
    search_ranking_bump=5.0,
    listed_pre_review=True,
    admin_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'line',
        applications.ANDROID.short: 'line',
    },
    can_primary_hero=True,
    can_be_compatible_with_all_fenix_versions=True,
    high_profile=True,
    high_profile_rating=True,
)

SPOTLIGHT = PromotedClass(
    id=5,
    name=_('Spotlight'),
    api_name='spotlight',
    listed_pre_review=True,
    admin_review=True,
    can_primary_hero=True,
    immediate_approval=True,
    high_profile=True,
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
    listed_pre_review=True,
    unlisted_pre_review=True,
    flag_for_human_review=True,
    high_profile=True,
)


# _VERIFIED and _SPONSORED should not be included, they are no longer valid
# promoted groups.
PROMOTED_GROUPS = [
    NOT_PROMOTED,
    RECOMMENDED,
    LINE,
    SPOTLIGHT,
    STRATEGIC,
    NOTABLE,
]

BADGED_GROUPS = [group for group in PROMOTED_GROUPS if group.badged]
BADGED_API_NAME = 'badged'  # Special alias for all badged groups

PROMOTED_GROUPS_BY_ID = {p.id: p for p in PROMOTED_GROUPS}
PROMOTED_API_NAME_TO_IDS = {
    **{p.api_name: [p.id] for p in PROMOTED_GROUPS if p},
    BADGED_API_NAME: [p.id for p in BADGED_GROUPS],
}
