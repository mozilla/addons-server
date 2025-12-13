from olympia.api.utils import APIChoices


PROMOTED_GROUP_CHOICES = APIChoices(
    ('RECOMMENDED', 1, 'Recommended', {'search_ranking_bump': 5.0}),
    ('LINE', 4, 'By Firefox', {'search_ranking_bump': 5.0}),
    ('SPOTLIGHT', 5, 'Spotlight'),
    ('STRATEGIC', 6, 'Strategic'),
    ('NOTABLE', 7, 'Notable'),
    ('SPONSORED', 8, 'Sponsored'),
    ('VERIFIED', 9, 'Verified'),
    ('PARTNER', 10, 'Partner'),
)

PROMOTED_GROUP_CHOICES.add_subset('BADGED', ('RECOMMENDED', 'LINE'))
PROMOTED_GROUP_CHOICES.add_subset(
    'ACTIVE', ('RECOMMENDED', 'LINE', 'SPOTLIGHT', 'STRATEGIC', 'NOTABLE', 'PARTNER')
)
# Note: SPONSORED & VERIFIED should not be included, they are no longer valid promoted
# groups

BADGED_API_NAME = 'badged'  # Special alias for all badged groups

PROMOTED_API_NAME_TO_IDS = {
    **{p.api_value: [p.value] for p in PROMOTED_GROUP_CHOICES.ACTIVE.entries},
    BADGED_API_NAME: [value for value in PROMOTED_GROUP_CHOICES.BADGED.values],
}
