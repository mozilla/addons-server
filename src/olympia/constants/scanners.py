from django.utils.translation import gettext_lazy as _


CUSTOMS = 1
# We do not use the WAT scanner anymore but we keep this constant for the model
# definition. We shouldn't use this constant, though.
# See: https://github.com/mozilla/addons-server/issues/19152
_WAT = 2
YARA = 3
MAD = 4

SCANNERS = {CUSTOMS: 'customs', _WAT: 'wat', YARA: 'yara', MAD: 'mad'}

# Action IDs are also used for severity (the higher, the more severe).
# The field is a PositiveSmallIntegerField, it should go up to 65535.
NO_ACTION = 1
FLAG_FOR_HUMAN_REVIEW = 20
DELAY_AUTO_APPROVAL = 100
DELAY_AUTO_APPROVAL_INDEFINITELY = 200
DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT = 300
DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT_FUTURE_APPROVALS = 400

ACTIONS = {
    NO_ACTION: _('No action'),
    FLAG_FOR_HUMAN_REVIEW: _('Flag for human review'),
    DELAY_AUTO_APPROVAL: _('Delay auto-approval'),
    DELAY_AUTO_APPROVAL_INDEFINITELY: _('Delay auto-approval indefinitely'),
    DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT: _(
        'Delay auto-approval indefinitely and add restrictions'
    ),
    DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT_FUTURE_APPROVALS: _(
        'Delay auto-approval indefinitely and add restrictions to future approvals'
    ),
}

UNKNOWN = None
TRUE_POSITIVE = 1
FALSE_POSITIVE = 2
INCONCLUSIVE = 3

RESULT_STATES = {
    UNKNOWN: _('Unknown'),
    TRUE_POSITIVE: _('True positive'),
    FALSE_POSITIVE: _('False positive'),
    INCONCLUSIVE: _('Inconclusive'),
}

NEW = 1
RUNNING = 2
ABORTED = 3
COMPLETED = 4
ABORTING = 5
SCHEDULED = 6

QUERY_RULE_STATES = {
    NEW: _('New'),
    RUNNING: _('Running'),
    ABORTED: _('Aborted'),
    ABORTING: _('Aborting'),
    COMPLETED: _('Completed'),
    SCHEDULED: _('Scheduled'),
}

LABEL_BAD = 'bad'
LABEL_GOOD = 'good'
