from olympia.api.utils import APIChoicesWithDash


APPEAL_EXPIRATION_DAYS = 184
REPORTED_MEDIA_BACKUP_EXPIRATION_DAYS = 31 + APPEAL_EXPIRATION_DAYS

DECISION_ACTIONS = APIChoicesWithDash(
    ('AMO_BAN_USER', 1, 'User ban'),
    ('AMO_DISABLE_ADDON', 2, 'Add-on disable'),
    ('AMO_ESCALATE_ADDON', 3, 'Escalate add-on to reviewers'),
    # 4 is unused
    ('AMO_DELETE_RATING', 5, 'Rating delete'),
    ('AMO_DELETE_COLLECTION', 6, 'Collection delete'),
    ('AMO_APPROVE', 7, 'Approved (no action)'),
    # Rejecting versions is not an available action for moderators in cinder
    # - it is only handled by the reviewer tools by AMO Reviewers.
    # It should not be sent by the cinder webhook, & does not have an action defined
    ('AMO_REJECT_VERSION_ADDON', 8, 'Add-on version reject'),
    ('AMO_REJECT_VERSION_WARNING_ADDON', 9, 'Add-on version delayed reject warning'),
)
DECISION_ACTIONS.add_subset(
    'APPEALABLE_BY_AUTHOR',
    (
        'AMO_BAN_USER',
        'AMO_DISABLE_ADDON',
        'AMO_DELETE_RATING',
        'AMO_DELETE_COLLECTION',
        'AMO_REJECT_VERSION_ADDON',
    ),
)
DECISION_ACTIONS.add_subset(
    'APPEALABLE_BY_REPORTER',
    ('AMO_APPROVE',),
)
DECISION_ACTIONS.add_subset(
    'UNRESOLVED',
    ('AMO_ESCALATE_ADDON',),
)
DECISION_ACTIONS.add_subset(
    'REMOVING',
    (
        'AMO_BAN_USER',
        'AMO_DISABLE_ADDON',
        'AMO_DELETE_RATING',
        'AMO_DELETE_COLLECTION',
        'AMO_REJECT_VERSION_ADDON',
    ),
)
