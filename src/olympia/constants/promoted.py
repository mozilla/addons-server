from olympia.api.utils import APIChoices


# This data should be kept in sync with the PromotedGroup model.
# If this list changes, we should update the relevant PromotedGroup instances
# via a data migration to add/remove the "active" field.
PROMOTED_GROUP_CHOICES = APIChoices(
    ('NOT_PROMOTED', 0, 'Not Promoted'),
    ('RECOMMENDED', 1, 'Recommended'),
    ('LINE', 4, 'By Firefox'),
    ('SPOTLIGHT', 5, 'Spotlight'),
    ('STRATEGIC', 6, 'Strategic'),
    ('NOTABLE', 7, 'Notable'),
    ('PARTNER', 10, 'Partner'),
)

BADGED_API_NAME = 'badged'  # Special alias for all badged groups
