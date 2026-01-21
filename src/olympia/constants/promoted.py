from types import DynamicClassAttribute

from olympia.amo.enum import EnumChoices


class _EnumChoicesWithSearchRankingBump(EnumChoices):
    @DynamicClassAttribute
    def search_ranking_bump(self):
        return {
            'RECOMMENDED': 5.0,
            'LINE': 5.0,
        }.get(self.name, 0.0)


class PROMOTED_GROUP_CHOICES(_EnumChoicesWithSearchRankingBump):
    RECOMMENDED = 1, 'Recommended'
    LINE = 4, 'By Firefox'
    SPOTLIGHT = 5, 'Spotlight'
    STRATEGIC = 6, 'Strategic'
    NOTABLE = 7, 'Notable'
    SPONSORED = 8, 'Sponsored'
    VERIFIED = 9, 'Verified'
    PARTNER = 10, 'Partner'


PROMOTED_GROUP_CHOICES.add_subset('BADGED', ('RECOMMENDED', 'LINE'))
PROMOTED_GROUP_CHOICES.add_subset(
    'ACTIVE', ('RECOMMENDED', 'LINE', 'SPOTLIGHT', 'STRATEGIC', 'NOTABLE', 'PARTNER')
)
# Note: SPONSORED & VERIFIED should not be included, they are no longer valid promoted
# groups

BADGED_API_NAME = 'badged'  # Special alias for all badged groups

PROMOTED_API_NAME_TO_IDS = {
    **{p.api_value: [p.value] for p in PROMOTED_GROUP_CHOICES.ACTIVE},
    BADGED_API_NAME: [value for value in PROMOTED_GROUP_CHOICES.BADGED.values],
}
