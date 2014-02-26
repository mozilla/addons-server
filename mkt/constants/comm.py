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

APPROVE_VERSION_WAITING = 8
ESCALATION_HIGH_ABUSE = 9
ESCALATION_HIGH_REFUNDS = 10
ESCALATION_CLEARED = 11
REREVIEW_CLEARED = 12

NOTE_TYPES = {
    NO_ACTION: _('No action'),
    APPROVAL: _('Approved'),
    REJECTION: _('Rejected'),
    DISABLED: _('Disabled'),
    MORE_INFO_REQUIRED: _('More information requested'),
    ESCALATION: _('Escalated'),
    REVIEWER_COMMENT: _('Comment'),
    RESUBMISSION: _('App resubmission'),
    APPROVE_VERSION_WAITING: _('Approved but waiting to be made public'),
    ESCALATION_CLEARED: _('Escalation cleared'),
    ESCALATION_HIGH_ABUSE: _('Escalated due to High Abuse Reports'),
    ESCALATION_HIGH_REFUNDS: _('Escalated due to High Refund Requests'),
    REREVIEW_CLEARED: _('Re-review cleared')
}


def NOTE_TYPES_JSON():
    return json.dumps(dict(
        (k, unicode(v)) for k, v in NOTE_TYPES.items()))


# Prefix of the reply to address in comm emails.
REPLY_TO_PREFIX = 'commreply+'


def U_NOTE_TYPES():
    return dict((key, unicode(value)) for (key, value) in
                NOTE_TYPES.iteritems())


def ACTION_MAP(activity_action):
    """Maps ActivityLog action ids to Commbadge note types."""
    import amo

    return {
        amo.LOG.APPROVE_VERSION.id: APPROVAL,
        amo.LOG.APPROVE_VERSION_WAITING.id: APPROVAL,
        amo.LOG.APP_DISABLED.id: DISABLED,
        amo.LOG.ESCALATE_MANUAL.id: ESCALATION,
        amo.LOG.ESCALATE_VERSION.id: ESCALATION,
        amo.LOG.ESCALATED_HIGH_ABUSE.id: ESCALATION_HIGH_ABUSE,
        amo.LOG.ESCALATED_HIGH_REFUNDS.id: ESCALATION_HIGH_REFUNDS,
        amo.LOG.ESCALATION_CLEARED.id: ESCALATION_CLEARED,
        amo.LOG.REQUEST_INFORMATION.id: MORE_INFO_REQUIRED,
        amo.LOG.REJECT_VERSION.id: REJECTION,
        amo.LOG.REREVIEW_CLEARED.id: REREVIEW_CLEARED,
        amo.LOG.WEBAPP_RESUBMIT.id: RESUBMISSION,
        amo.LOG.COMMENT_VERSION.id: REVIEWER_COMMENT,
    }.get(activity_action, NO_ACTION)
