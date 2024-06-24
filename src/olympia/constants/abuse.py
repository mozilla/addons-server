from olympia.api.utils import APIChoicesWithDash, APIChoicesWithNone


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
    # Approving new versions is not an available action for moderators in cinder
    ('AMO_APPROVE_VERSION', 10, 'Approved (new version approval)'),
    ('AMO_IGNORE', 11, 'Invalid report, so ignored'),
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
    ('AMO_APPROVE', 'AMO_APPROVE_VERSION'),
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
DECISION_ACTIONS.add_subset(
    'APPROVING',
    ('AMO_APPROVE', 'AMO_APPROVE_VERSION'),
)

# Illegal categories, only used when the reason is `illegal`. The constants
# are derived from the "spec" but without the `STATEMENT_CATEGORY_` prefix.
# The `illegal_category_cinder_value` property will return the correct value
# to send to Cinder.
ILLEGAL_CATEGORIES = APIChoicesWithNone(
    ('ANIMAL_WELFARE', 1, 'Animal welfare'),
    (
        'CONSUMER_INFORMATION',
        2,
        'Consumer information infringements',
    ),
    (
        'DATA_PROTECTION_AND_PRIVACY_VIOLATIONS',
        3,
        'Data protection and privacy violations',
    ),
    (
        'ILLEGAL_OR_HARMFUL_SPEECH',
        4,
        'Illegal or harmful speech',
    ),
    (
        'INTELLECTUAL_PROPERTY_INFRINGEMENTS',
        5,
        'Intellectual property infringements',
    ),
    (
        'NEGATIVE_EFFECTS_ON_CIVIC_DISCOURSE_OR_ELECTIONS',
        6,
        'Negative effects on civic discourse or elections',
    ),
    ('NON_CONSENSUAL_BEHAVIOUR', 7, 'Non-consensual behavior'),
    (
        'PORNOGRAPHY_OR_SEXUALIZED_CONTENT',
        8,
        'Pornography or sexualized content',
    ),
    ('PROTECTION_OF_MINORS', 9, 'Protection of minors'),
    ('RISK_FOR_PUBLIC_SECURITY', 10, 'Risk for public security'),
    ('SCAMS_AND_FRAUD', 11, 'Scams or fraud'),
    ('SELF_HARM', 12, 'Self-harm'),
    (
        'UNSAFE_AND_PROHIBITED_PRODUCTS',
        13,
        'Unsafe, non-compliant, or prohibited products',
    ),
    ('VIOLENCE', 14, 'Violence'),
    ('OTHER', 15, 'Other'),
)
