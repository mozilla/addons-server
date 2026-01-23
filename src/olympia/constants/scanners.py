CUSTOMS = 1
# We do not use the WAT or MAD scanners anymore but we keep these constants for the
# model definition. We shouldn't use these constants, though.
_WAT = 2
YARA = 3
_MAD = 4
NARC = 5
WEBHOOK = 6

SCANNERS = {
    CUSTOMS: 'customs',
    _WAT: 'wat',
    YARA: 'yara',
    _MAD: 'mad',
    NARC: 'narc',
    WEBHOOK: 'webhook',
}

# Action IDs are also used for severity (the higher, the more severe).
# The field is a PositiveSmallIntegerField, it should go up to 65535.
NO_ACTION = 1
FLAG_FOR_HUMAN_REVIEW = 20
DELAY_AUTO_APPROVAL = 100
DELAY_AUTO_APPROVAL_INDEFINITELY = 200
DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT = 300
DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT_FUTURE_APPROVALS = 400
DISABLE_AND_BLOCK = 500


ACTIONS = {
    NO_ACTION: 'No action',
    FLAG_FOR_HUMAN_REVIEW: 'Flag for human review',
    DELAY_AUTO_APPROVAL: 'Delay auto-approval',
    DELAY_AUTO_APPROVAL_INDEFINITELY: 'Delay auto-approval indefinitely',
    DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT: (
        'Delay auto-approval indefinitely and add restrictions'
    ),
    DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT_FUTURE_APPROVALS: (
        'Delay auto-approval indefinitely and add restrictions to future approvals'
    ),
    DISABLE_AND_BLOCK: ('Force-disable and block'),
}

UNKNOWN = None
TRUE_POSITIVE = 1
FALSE_POSITIVE = 2
INCONCLUSIVE = 3

RESULT_STATES = {
    UNKNOWN: 'Unknown',
    TRUE_POSITIVE: 'True positive',
    FALSE_POSITIVE: 'False positive',
    INCONCLUSIVE: 'Inconclusive',
}

NEW = 1
RUNNING = 2
ABORTED = 3
COMPLETED = 4
ABORTING = 5
SCHEDULED = 6

QUERY_RULE_STATES = {
    NEW: 'New',
    RUNNING: 'Running',
    ABORTED: 'Aborted',
    ABORTING: 'Aborting',
    COMPLETED: 'Completed',
    SCHEDULED: 'Scheduled',
}

LABEL_BAD = 'bad'
LABEL_GOOD = 'good'

# Webhook events
WEBHOOK_DURING_VALIDATION = 1
WEBHOOK_ON_SOURCE_CODE_UPLOADED = 2

WEBHOOK_EVENTS = {
    WEBHOOK_DURING_VALIDATION: 'during_validation',
    WEBHOOK_ON_SOURCE_CODE_UPLOADED: 'on_source_code_uploaded',
}

# Special empty configuration schema to use when the rule is being created
EMPTY_RULE_CONFIGURATION_SCHEMA = {}

# Default configuration for rules other than NARC
DEFAULT_RULE_CONFIGURATION_SCHEMA = {}

# Narc configuration schema
NARC_RULE_CONFIGURATION_SCHEMA = {
    'type': 'object',
    'keys': {
        'examine_slug': {
            'type': 'boolean',
            'default': False,
            'helpText': (
                'Run the rule against the add-on slug used for the listing on AMO'
            ),
        },
        'examine_listing_names': {
            'type': 'boolean',
            'default': True,
            'helpText': (
                'Run the rule against the add-on name(s) used for the listing on AMO'
            ),
        },
        'examine_xpi_names': {
            'type': 'boolean',
            'default': True,
            'helpText': 'Run the rule against the add-on name(s) in the XPI',
        },
        'examine_authors_names': {
            'type': 'boolean',
            'default': True,
            'helpText': (
                'Run the rule against the name of each author attached to the add-on'
            ),
        },
        'examine_normalized_variants': {
            'type': 'boolean',
            'default': True,
            'helpText': (
                'For each string being examined, also examine a normalized variant'
            ),
        },
        'examine_homoglyphs_variants': {
            'type': 'boolean',
            'default': True,
            'helpText': (
                'For each string being examined, also examine homoglyphs variants',
            )
        },
    },
}
