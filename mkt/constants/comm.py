import json

from tower import ugettext_lazy as _


# Number of days a token is valid for.
THREAD_TOKEN_EXPIRY = 30

# Number of times a token can be used.
MAX_TOKEN_USE_COUNT = 5

MAX_ATTACH = 10

NO_ACTION = 0
APPROVAL = 1
REJECTION = 2
DISABLED = 3
MORE_INFO_REQUIRED = 4
ESCALATION = 5
REVIEWER_COMMENT = 6
RESUBMISSION = 7

NOTE_TYPES = {
    NO_ACTION: _('No action'),
    APPROVAL: _('Approved'),
    REJECTION: _('Rejected'),
    DISABLED: _('Disabled'),
    MORE_INFO_REQUIRED: _('More information requested'),
    ESCALATION: _('Escalated'),
    REVIEWER_COMMENT: _('Comment'),
    RESUBMISSION: _('App Resubmission'),
}

def NOTE_TYPES_JSON():
    return json.dumps(dict(
        (k, unicode(v)) for k, v in NOTE_TYPES.items()))

# Prefix of the reply to address in comm emails.
REPLY_TO_PREFIX = 'reply+'
