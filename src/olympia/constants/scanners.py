from django.utils.translation import ugettext_lazy as _


CUSTOMS = 1
WAT = 2
YARA = 3

SCANNERS = {
    CUSTOMS: 'customs',
    WAT: 'wat',
    YARA: 'yara',
}

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
