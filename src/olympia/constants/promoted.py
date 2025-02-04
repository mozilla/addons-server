from olympia.api.utils import APIChoicesWithNone


PROMOTED_GROUP_CHOICES = APIChoicesWithNone(
    ('NOT_PROMOTED', 0, 'Not Promoted'),
    ('RECOMMENDED', 1, 'Recommended'),
    ('LINE', 4, 'By Firefox'),
    ('SPOTLIGHT', 5, 'Spotlight'),
    ('STRATEGIC', 6, 'Strategic'),
    ('NOTABLE', 7, 'Notable'),
    ('SPONSORED', 8, 'Sponsored'),
    ('VERIFIED', 9, 'Verified'),
)

DEACTIVATED_LEGACY_IDS = [
    PROMOTED_GROUP_CHOICES.SPONSORED,
    PROMOTED_GROUP_CHOICES.VERIFIED,
]

BADGED_API_NAME = 'badged'  # Special alias for all badged groups
