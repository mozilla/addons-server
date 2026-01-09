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

WEBHOOK_EVENTS = {
    WEBHOOK_DURING_VALIDATION: 'during_validation',
}
