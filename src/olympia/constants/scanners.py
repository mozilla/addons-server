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
NO_ACTION = 1
FLAG_FOR_HUMAN_REVIEW = 20

ACTIONS = {
    NO_ACTION: _('no action'),
    FLAG_FOR_HUMAN_REVIEW: _('flag for human review'),
}
