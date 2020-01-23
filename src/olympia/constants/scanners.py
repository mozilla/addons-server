from django.utils.translation import ugettext_lazy as _


CUSTOMS = 1
WAT = 2
YARA = 3
ML_API = 4

SCANNERS = {CUSTOMS: 'customs', WAT: 'wat', YARA: 'yara', ML_API: 'ml_api'}

# Action IDs are also used for severity (the higher, the more severe).
# The field is a PositiveSmallIntegerField, it should go up to 65535.
NO_ACTION = 1
FLAG_FOR_HUMAN_REVIEW = 20
DELAY_AUTO_APPROVAL = 100
DELAY_AUTO_APPROVAL_INDEFINITELY = 200

ACTIONS = {
    NO_ACTION: _('No action'),
    FLAG_FOR_HUMAN_REVIEW: _('Flag for human review'),
    DELAY_AUTO_APPROVAL: _('Delay auto-approval'),
    DELAY_AUTO_APPROVAL_INDEFINITELY: _('Delay auto-approval indefinitely'),
}

UNKNOWN = None
TRUE_POSITIVE = 1
FALSE_POSITIVE = 2

RESULT_STATES = {
    UNKNOWN: _('Unknown'),
    TRUE_POSITIVE: _('True positive'),
    FALSE_POSITIVE: _('False positive'),
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
