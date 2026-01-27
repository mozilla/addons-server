from enum import StrEnum

from olympia.amo.enum import EnumChoices, EnumChoicesApiDash


APPEAL_EXPIRATION_DAYS = 184
REPORTED_MEDIA_BACKUP_EXPIRATION_DAYS = 31 + APPEAL_EXPIRATION_DAYS


class DECISION_ACTIONS(EnumChoicesApiDash):
    AMO_BAN_USER = 1, 'User ban'
    AMO_DISABLE_ADDON = 2, 'Add-on disable'
    # Used to indicate the job has been forwarded to AMO
    AMO_ESCALATE_ADDON = 3, '(Obsolete) Forward add-on to reviewers'
    # 4 is unused
    AMO_DELETE_RATING = 5, 'Rating delete'
    AMO_DELETE_COLLECTION = 6, 'Collection delete'
    AMO_APPROVE = 7, 'Approved (no action)'
    # Rejecting versions is not an available action for moderators in cinder
    # - it is only handled by the reviewer tools by AMO Reviewers.
    # It should not be sent by the cinder webhook, & does not have an action defined
    AMO_REJECT_VERSION_ADDON = 8, 'Add-on version reject'
    AMO_REJECT_VERSION_WARNING_ADDON = 9, 'Add-on version delayed reject warning'
    # Approving new versions is not an available action for moderators in cinder
    AMO_APPROVE_VERSION = 10, 'Approved (new version approval)'
    AMO_IGNORE = 11, 'Invalid report, so ignored'
    AMO_CLOSED_NO_ACTION = 12, 'Content already moderated (no action)'
    AMO_LEGAL_FORWARD = 13, 'Forward add-on to legal'
    # Changing pending rejection date is not an available action for moderators
    # in cinder - it is only performed by AMO Reviewers.
    AMO_CHANGE_PENDING_REJECTION_DATE = 14, 'Pending rejection date changed'
    AMO_REQUEUE = 15, 'No action - internal requeue'
    AMO_BLOCK_ADDON = 16, 'Add-on disable and block'
    AMO_REJECT_LISTING_CONTENT = 17, 'Add-on listing content rejection'


DECISION_ACTIONS.add_subset(
    'APPEALABLE_BY_AUTHOR',
    (
        'AMO_BAN_USER',
        'AMO_DISABLE_ADDON',
        'AMO_DELETE_RATING',
        'AMO_DELETE_COLLECTION',
        'AMO_REJECT_VERSION_ADDON',
        # Note: AMO_BLOCK_ADDON is appealable, but at the moment the blocking
        # part can't be automatically reverted by a successful appeal and has
        # to be done manually.
        'AMO_BLOCK_ADDON',
        'AMO_REJECT_LISTING_CONTENT',
    ),
)
DECISION_ACTIONS.add_subset(
    'APPEALABLE_BY_REPORTER', ('AMO_APPROVE', 'AMO_APPROVE_VERSION')
)
DECISION_ACTIONS.add_subset(
    'REMOVING',
    (
        'AMO_BAN_USER',
        'AMO_DISABLE_ADDON',
        'AMO_DELETE_RATING',
        'AMO_DELETE_COLLECTION',
        'AMO_REJECT_VERSION_ADDON',
        'AMO_BLOCK_ADDON',
        'AMO_REJECT_LISTING_CONTENT',
    ),
)
DECISION_ACTIONS.add_subset(
    'NON_OFFENDING', ('AMO_APPROVE', 'AMO_APPROVE_VERSION', 'AMO_IGNORE')
)
DECISION_ACTIONS.add_subset(
    'SKIP_DECISION',
    (
        'AMO_APPROVE',
        'AMO_APPROVE_VERSION',
        'AMO_LEGAL_FORWARD',
        'AMO_CHANGE_PENDING_REJECTION_DATE',
    ),
)


# Illegal categories, only used when the reason is `illegal`. The constants
# are derived from the "spec" but without the `STATEMENT_CATEGORY_` prefix.
# The `illegal_category_cinder_value` property will return the correct value
# to send to Cinder.
class ILLEGAL_CATEGORIES(EnumChoices):
    ANIMAL_WELFARE = 1, 'Animal welfare'
    CONSUMER_INFORMATION = 2, 'Consumer information infringements'
    DATA_PROTECTION_AND_PRIVACY_VIOLATIONS = 3, 'Data protection and privacy violations'
    ILLEGAL_OR_HARMFUL_SPEECH = 4, 'Illegal or harmful speech'
    INTELLECTUAL_PROPERTY_INFRINGEMENTS = 5, 'Intellectual property infringements'
    NEGATIVE_EFFECTS_ON_CIVIC_DISCOURSE_OR_ELECTIONS = (
        6,
        'Negative effects on civic discourse or elections',
    )
    NON_CONSENSUAL_BEHAVIOUR = 7, 'Non-consensual behavior'
    PORNOGRAPHY_OR_SEXUALIZED_CONTENT = 8, 'Pornography or sexualized content'
    PROTECTION_OF_MINORS = 9, 'Protection of minors'
    RISK_FOR_PUBLIC_SECURITY = 10, 'Risk for public security'
    SCAMS_AND_FRAUD = 11, 'Scams or fraud'
    SELF_HARM = 12, 'Self-harm'
    UNSAFE_AND_PROHIBITED_PRODUCTS = 13, 'Unsafe, non-compliant, or prohibited products'
    VIOLENCE = 14, 'Violence'
    OTHER = 15, 'Other'

    __empty__ = 'None'


class ILLEGAL_SUBCATEGORIES(EnumChoices):
    OTHER = 1, 'Something else'
    # CONSUMER_INFORMATION
    INSUFFICIENT_INFORMATION_ON_TRADERS = 2, 'Insufficient information on traders'
    NONCOMPLIANCE_PRICING = 3, 'Non-compliance with pricing regulations'
    HIDDEN_ADVERTISEMENT = (
        4,
        'Hidden advertisement or commercial communication, including by influencers',
    )
    MISLEADING_INFO_GOODS_SERVICES = (
        5,
        'Misleading information about the characteristics of the goods and services',
    )
    MISLEADING_INFO_CONSUMER_RIGHTS = (
        6,
        'Misleading information about the consumer’s rights',
    )
    # DATA_PROTECTION_AND_PRIVACY_VIOLATIONS
    BIOMETRIC_DATA_BREACH = 7, 'Biometric data breach'
    MISSING_PROCESSING_GROUND = 8, 'Missing processing ground for data'
    RIGHT_TO_BE_FORGOTTEN = 9, 'Right to be forgotten'
    DATA_FALSIFICATION = 10, 'Data falsification'
    # ILLEGAL_OR_HARMFUL_SPEECH
    DEFAMATION = 11, 'Defamation'
    DISCRIMINATION = 12, 'Discrimination'
    HATE_SPEECH = (
        13,
        'Illegal incitement to violence and hatred based on protected '
        'characteristics (hate speech)',
    )
    # INTELLECTUAL_PROPERTY_INFRINGEMENTS
    # Note: `KEYWORD_COPYRIGHT_INFRINGEMENT` and
    # `KEYWORD_TRADEMARK_INFRINGEMENT` are currently not defined.
    DESIGN_INFRINGEMENT = 14, 'Design infringements'
    GEOGRAPHIC_INDICATIONS_INFRINGEMENT = 15, 'Geographical indications infringements'
    PATENT_INFRINGEMENT = 16, 'Patent infringements'
    TRADE_SECRET_INFRINGEMENT = 17, 'Trade secret infringements'
    # NEGATIVE_EFFECTS_ON_CIVIC_DISCOURSE_OR_ELECTIONS
    VIOLATION_EU_LAW = (
        18,
        'Violation of EU law relevant to civic discourse or elections',
    )
    VIOLATION_NATIONAL_LAW = (
        19,
        'Violation of national law relevant to civic discourse or elections',
    )
    MISINFORMATION_DISINFORMATION_DISINFORMATION = (
        20,
        'Misinformation, disinformation, foreign information manipulation '
        'and interference',
    )
    # NON_CONSENSUAL_BEHAVIOUR
    NON_CONSENSUAL_IMAGE_SHARING = 21, 'Non-consensual image sharing'
    NON_CONSENSUAL_ITEMS_DEEPFAKE = (
        22,
        'Non-consensual items containing deepfake or similar technology using '
        "a third party's features",
    )
    ONLINE_BULLYING_INTIMIDATION = 23, 'Online bullying/intimidation'
    STALKING = 24, 'Stalking'
    # PORNOGRAPHY_OR_SEXUALIZED_CONTENT
    ADULT_SEXUAL_MATERIAL = 25, 'Adult sexual material'
    IMAGE_BASED_SEXUAL_ABUSE = (
        26,
        'Image-based sexual abuse (excluding content depicting minors)',
    )
    # PROTECTION_OF_MINORS
    # Note: `KEYWORD_UNSAFE_CHALLENGES` is not defined on purpose.
    AGE_SPECIFIC_RESTRICTIONS_MINORS = 27, 'Age-specific restrictions concerning minors'
    CHILD_SEXUAL_ABUSE_MATERIAL = 28, 'Child sexual abuse material'
    GROOMING_SEXUAL_ENTICEMENT_MINORS = 29, 'Grooming/sexual enticement of minors'
    # RISK_FOR_PUBLIC_SECURITY
    ILLEGAL_ORGANIZATIONS = 30, 'Illegal organizations'
    RISK_ENVIRONMENTAL_DAMAGE = 31, 'Risk for environmental damage'
    RISK_PUBLIC_HEALTH = 32, 'Risk for public health'
    TERRORIST_CONTENT = 33, 'Terrorist content'
    # SCAMS_AND_FRAUD
    INAUTHENTIC_ACCOUNTS = 34, 'Inauthentic accounts'
    INAUTHENTIC_LISTINGS = 35, 'Inauthentic listings'
    INAUTHENTIC_USER_REVIEWS = 36, 'Inauthentic user reviews'
    IMPERSONATION_ACCOUNT_HIJACKING = 37, 'Impersonation or account hijacking'
    PHISHING = 38, 'Phishing'
    PYRAMID_SCHEMES = 39, 'Pyramid schemes'
    # SELF_HARM
    CONTENT_PROMOTING_EATING_DISORDERS = 40, 'Content promoting eating disorders'
    SELF_MUTILATION = 41, 'Self-mutilation'
    SUICIDE = 42, 'Suicide'
    # UNSAFE_AND_PROHIBITED_PRODUCTS
    PROHIBITED_PRODUCTS = 43, 'Prohibited or restricted products'
    UNSAFE_PRODUCTS = 44, 'Unsafe or non-compliant products'
    # VIOLENCE
    COORDINATED_HARM = 45, 'Coordinated harm'
    GENDER_BASED_VIOLENCE = 46, 'Gender-based violence'
    HUMAN_EXPLOITATION = 47, 'Human exploitation'
    HUMAN_TRAFFICKING = 48, 'Human trafficking'
    INCITEMENT_VIOLENCE_HATRED = (
        49,
        'General calls or incitement to violence and/or hatred',
    )
    # ANIMAL_WELFARE
    #
    # Note: `KEYWORD_ANIMAL_HARM` and `KEYWORD_UNLAWFUL_SALE_ANIMALS` are
    # curently not defined.

    __empty__ = 'None'


ILLEGAL_SUBCATEGORIES_BY_CATEGORY = {
    ILLEGAL_CATEGORIES.ANIMAL_WELFARE: [
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.CONSUMER_INFORMATION: [
        ILLEGAL_SUBCATEGORIES.INSUFFICIENT_INFORMATION_ON_TRADERS,
        ILLEGAL_SUBCATEGORIES.NONCOMPLIANCE_PRICING,
        ILLEGAL_SUBCATEGORIES.HIDDEN_ADVERTISEMENT,
        ILLEGAL_SUBCATEGORIES.MISLEADING_INFO_GOODS_SERVICES,
        ILLEGAL_SUBCATEGORIES.MISLEADING_INFO_CONSUMER_RIGHTS,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.DATA_PROTECTION_AND_PRIVACY_VIOLATIONS: [
        ILLEGAL_SUBCATEGORIES.BIOMETRIC_DATA_BREACH,
        ILLEGAL_SUBCATEGORIES.MISSING_PROCESSING_GROUND,
        ILLEGAL_SUBCATEGORIES.RIGHT_TO_BE_FORGOTTEN,
        ILLEGAL_SUBCATEGORIES.DATA_FALSIFICATION,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.ILLEGAL_OR_HARMFUL_SPEECH: [
        ILLEGAL_SUBCATEGORIES.DEFAMATION,
        ILLEGAL_SUBCATEGORIES.DISCRIMINATION,
        ILLEGAL_SUBCATEGORIES.HATE_SPEECH,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.INTELLECTUAL_PROPERTY_INFRINGEMENTS: [
        ILLEGAL_SUBCATEGORIES.DESIGN_INFRINGEMENT,
        ILLEGAL_SUBCATEGORIES.GEOGRAPHIC_INDICATIONS_INFRINGEMENT,
        ILLEGAL_SUBCATEGORIES.PATENT_INFRINGEMENT,
        ILLEGAL_SUBCATEGORIES.TRADE_SECRET_INFRINGEMENT,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.NEGATIVE_EFFECTS_ON_CIVIC_DISCOURSE_OR_ELECTIONS: [
        ILLEGAL_SUBCATEGORIES.VIOLATION_EU_LAW,
        ILLEGAL_SUBCATEGORIES.VIOLATION_NATIONAL_LAW,
        ILLEGAL_SUBCATEGORIES.MISINFORMATION_DISINFORMATION_DISINFORMATION,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.NON_CONSENSUAL_BEHAVIOUR: [
        ILLEGAL_SUBCATEGORIES.NON_CONSENSUAL_IMAGE_SHARING,
        ILLEGAL_SUBCATEGORIES.NON_CONSENSUAL_ITEMS_DEEPFAKE,
        ILLEGAL_SUBCATEGORIES.ONLINE_BULLYING_INTIMIDATION,
        ILLEGAL_SUBCATEGORIES.STALKING,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.PORNOGRAPHY_OR_SEXUALIZED_CONTENT: [
        ILLEGAL_SUBCATEGORIES.ADULT_SEXUAL_MATERIAL,
        ILLEGAL_SUBCATEGORIES.IMAGE_BASED_SEXUAL_ABUSE,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.PROTECTION_OF_MINORS: [
        ILLEGAL_SUBCATEGORIES.AGE_SPECIFIC_RESTRICTIONS_MINORS,
        ILLEGAL_SUBCATEGORIES.CHILD_SEXUAL_ABUSE_MATERIAL,
        ILLEGAL_SUBCATEGORIES.GROOMING_SEXUAL_ENTICEMENT_MINORS,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.RISK_FOR_PUBLIC_SECURITY: [
        ILLEGAL_SUBCATEGORIES.ILLEGAL_ORGANIZATIONS,
        ILLEGAL_SUBCATEGORIES.RISK_ENVIRONMENTAL_DAMAGE,
        ILLEGAL_SUBCATEGORIES.RISK_PUBLIC_HEALTH,
        ILLEGAL_SUBCATEGORIES.TERRORIST_CONTENT,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.SCAMS_AND_FRAUD: [
        ILLEGAL_SUBCATEGORIES.INAUTHENTIC_ACCOUNTS,
        ILLEGAL_SUBCATEGORIES.INAUTHENTIC_LISTINGS,
        ILLEGAL_SUBCATEGORIES.INAUTHENTIC_USER_REVIEWS,
        ILLEGAL_SUBCATEGORIES.IMPERSONATION_ACCOUNT_HIJACKING,
        ILLEGAL_SUBCATEGORIES.PHISHING,
        ILLEGAL_SUBCATEGORIES.PYRAMID_SCHEMES,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.SELF_HARM: [
        ILLEGAL_SUBCATEGORIES.CONTENT_PROMOTING_EATING_DISORDERS,
        ILLEGAL_SUBCATEGORIES.SELF_MUTILATION,
        ILLEGAL_SUBCATEGORIES.SUICIDE,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.UNSAFE_AND_PROHIBITED_PRODUCTS: [
        ILLEGAL_SUBCATEGORIES.PROHIBITED_PRODUCTS,
        ILLEGAL_SUBCATEGORIES.UNSAFE_PRODUCTS,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.VIOLENCE: [
        ILLEGAL_SUBCATEGORIES.COORDINATED_HARM,
        ILLEGAL_SUBCATEGORIES.GENDER_BASED_VIOLENCE,
        ILLEGAL_SUBCATEGORIES.HUMAN_EXPLOITATION,
        ILLEGAL_SUBCATEGORIES.HUMAN_TRAFFICKING,
        ILLEGAL_SUBCATEGORIES.INCITEMENT_VIOLENCE_HATRED,
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
    ILLEGAL_CATEGORIES.OTHER: [
        ILLEGAL_SUBCATEGORIES.OTHER,
    ],
}


class DECISION_SOURCES(StrEnum):
    AUTOMATION = 'Automation'
    REVIEWER = 'AMO Reviewer'
    LEGAL = 'Legal'
    TASKUS = 'TaskUs'
