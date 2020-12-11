# The absolute import feature is required so that we get the root celery
# module rather than `amo.celery`.
from __future__ import absolute_import

from collections import namedtuple
from inspect import isclass

from django.utils.translation import ugettext_lazy as _


__all__ = (
    'LOG',
    'LOG_BY_ID',
    'LOG_KEEP',
)


class _LOG(object):
    action_class = None


class CREATE_ADDON(_LOG):
    id = 1
    action_class = 'add'
    format = _('{addon} was created.')
    keep = True


class EDIT_PROPERTIES(_LOG):
    """ Expects: addon """

    id = 2
    action_class = 'edit'
    format = _('{addon} properties edited.')


class EDIT_DESCRIPTIONS(_LOG):
    id = 3
    action_class = 'edit'
    format = _('{addon} description edited.')


class EDIT_CATEGORIES(_LOG):
    id = 4
    action_class = 'edit'
    format = _('Categories edited for {addon}.')


class ADD_USER_WITH_ROLE(_LOG):
    id = 5
    action_class = 'add'
    format = _('{0.name} ({1}) added to {addon}.')
    keep = True


class REMOVE_USER_WITH_ROLE(_LOG):
    id = 6
    action_class = 'delete'
    # L10n: {0} is the user being removed, {1} is their role.
    format = _('{0.name} ({1}) removed from {addon}.')
    keep = True


class EDIT_CONTRIBUTIONS(_LOG):
    id = 7
    action_class = 'edit'
    format = _('Contributions for {addon}.')


class USER_DISABLE(_LOG):
    id = 8
    format = _('{addon} disabled.')
    keep = True


class USER_ENABLE(_LOG):
    id = 9
    format = _('{addon} enabled.')
    keep = True


class CHANGE_STATUS(_LOG):
    id = 12
    # L10n: {status} is the status
    format = _('{addon} status changed to {status}.')
    keep = True


class ADD_VERSION(_LOG):
    id = 16
    action_class = 'add'
    format = _('{version} added to {addon}.')
    keep = True


class EDIT_VERSION(_LOG):
    id = 17
    action_class = 'edit'
    format = _('{version} edited for {addon}.')


class DELETE_VERSION(_LOG):
    id = 18
    action_class = 'delete'
    # Note, {0} is a string not a version since the version is deleted.
    # L10n: {0} is the version number
    format = _('Version {0} deleted from {addon}.')
    keep = True


class ADD_FILE_TO_VERSION(_LOG):
    id = 19
    action_class = 'add'
    format = _('File {0.name} added to {version} of {addon}.')


class DELETE_FILE_FROM_VERSION(_LOG):
    """
    Expecting: addon, filename, version
    Because the file is being deleted, filename and version
    should be strings and not the object.
    """

    id = 20
    action_class = 'delete'
    format = _('File {0} deleted from {version} of {addon}.')


class APPROVE_VERSION(_LOG):
    id = 21
    action_class = 'approve'
    format = _('{addon} {version} approved.')
    short = _('Approved')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class PRELIMINARY_VERSION(_LOG):
    id = 42
    action_class = 'approve'
    format = _('{addon} {version} given preliminary review.')
    short = _('Preliminarily approved')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class REJECT_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 43
    action_class = 'reject'
    format = _('{addon} {version} rejected.')
    short = _('Rejected')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class RETAIN_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 22
    format = _('{addon} {version} retained.')
    short = _('Retained')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class ESCALATE_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 23
    format = _('{addon} {version} escalated.')
    short = _('Super review requested')
    keep = True
    review_email_user = True
    review_queue = True
    hide_developer = True


class REQUEST_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 24
    format = _('{addon} {version} review requested.')
    short = _('Review requested')
    keep = True
    review_email_user = True
    review_queue = True


# Obsolete now that we have pending rejections, kept for compatibility.
class REQUEST_INFORMATION(_LOG):
    id = 44
    format = _('{addon} {version} more information requested.')
    short = _('More information requested')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


# Obsolete now that we've split the requests for admin review into separate
# actions for code/theme/content, but kept for compatibility with old history,
# and also to re-use the `sanitize` property.
class REQUEST_SUPER_REVIEW(_LOG):
    id = 45
    format = _('{addon} {version} super review requested.')
    short = _('Super review requested')
    keep = True
    review_queue = True
    sanitize = _(
        "The addon has been flagged for Admin Review.  It's still "
        'in our review queue, but it will need to be checked by one '
        'of our admin reviewers. The review might take longer than '
        'usual.'
    )
    reviewer_review_action = True


class COMMENT_VERSION(_LOG):
    id = 49
    format = _('Comment on {addon} {version}.')
    short = _('Commented')
    keep = True
    review_queue = True
    hide_developer = True
    reviewer_review_action = True


class ADD_TAG(_LOG):
    id = 25
    action_class = 'tag'
    format = _('{tag} added to {addon}.')


class REMOVE_TAG(_LOG):
    id = 26
    action_class = 'tag'
    format = _('{tag} removed from {addon}.')


class ADD_TO_COLLECTION(_LOG):
    id = 27
    action_class = 'collection'
    format = _('{addon} added to {collection}.')


class REMOVE_FROM_COLLECTION(_LOG):
    id = 28
    action_class = 'collection'
    format = _('{addon} removed from {collection}.')


class ADD_RATING(_LOG):
    id = 29
    action_class = 'review'
    format = _('{rating} for {addon} written.')


# TODO(davedash): Add these when we do the admin site
class ADD_RECOMMENDED_CATEGORY(_LOG):
    id = 31
    action_class = 'edit'
    # L10n: {0} is a category name.
    format = _('{addon} featured in {0}.')


class REMOVE_RECOMMENDED_CATEGORY(_LOG):
    id = 32
    action_class = 'edit'
    # L10n: {0} is a category name.
    format = _('{addon} no longer featured in {0}.')


class ADD_RECOMMENDED(_LOG):
    id = 33
    format = _('{addon} is now featured.')
    keep = True


class REMOVE_RECOMMENDED(_LOG):
    id = 34
    format = _('{addon} is no longer featured.')
    keep = True


class ADD_APPVERSION(_LOG):
    id = 35
    action_class = 'add'
    # L10n: {0} is the application, {1} is the version of the app
    format = _('{0} {1} added.')


class CHANGE_USER_WITH_ROLE(_LOG):
    """ Expects: author.user, role, addon """

    id = 36
    # L10n: {0} is a user, {1} is their role
    format = _('{0.name} role changed to {1} for {addon}.')
    keep = True


class CHANGE_LICENSE(_LOG):
    """ Expects: license, addon """

    id = 37
    action_class = 'edit'
    format = _('{addon} is now licensed under {0}.')


class CHANGE_POLICY(_LOG):
    id = 38
    action_class = 'edit'
    format = _('{addon} policy changed.')


class CHANGE_ICON(_LOG):
    id = 39
    action_class = 'edit'
    format = _('{addon} icon changed.')


class APPROVE_RATING(_LOG):
    id = 40
    action_class = 'approve'
    format = _('{rating} for {addon} approved.')
    reviewer_format = _('{user} approved {rating} for {addon}.')
    keep = True
    reviewer_event = True


class DELETE_RATING(_LOG):
    """Requires rating.id and add-on objects."""

    id = 41
    action_class = 'review'
    format = _('Review {rating} for {addon} deleted.')
    reviewer_format = _('{user} deleted {rating} for {addon}.')
    keep = True
    reviewer_event = True


class MAX_APPVERSION_UPDATED(_LOG):
    id = 46
    format = _('Application max version for {version} updated.')


class BULK_VALIDATION_EMAILED(_LOG):
    id = 47
    format = _('Authors emailed about compatibility of {version}.')


class BULK_VALIDATION_USER_EMAILED(_LOG):
    id = 130
    format = _('Email sent to Author about add-on compatibility.')


class CHANGE_PASSWORD(_LOG):
    id = 48
    format = _('Password changed.')


class APPROVE_VERSION_WAITING(_LOG):
    id = 53
    action_class = 'approve'
    format = _('{addon} {version} approved but waiting to be made public.')
    short = _('Approved but waiting')
    keep = True
    review_email_user = True
    review_queue = True


class USER_EDITED(_LOG):
    id = 60
    format = _('Account updated.')


class CUSTOM_TEXT(_LOG):
    id = 98
    format = '{0}'


class CUSTOM_HTML(_LOG):
    id = 99
    format = '{0}'


class OBJECT_ADDED(_LOG):
    id = 100
    format = _('Created: {0}.')
    admin_event = True


class OBJECT_EDITED(_LOG):
    id = 101
    format = _('Edited field: {2} set to: {0}.')
    admin_event = True


class OBJECT_DELETED(_LOG):
    id = 102
    format = _('Deleted: {1}.')
    admin_event = True


class ADMIN_USER_EDITED(_LOG):
    id = 103
    format = _('User {user} edited, reason: {1}')
    admin_event = True


class ADMIN_USER_ANONYMIZED(_LOG):
    id = 104
    format = _('User {user} anonymized.')
    keep = True
    admin_event = True


class ADMIN_USER_RESTRICTED(_LOG):
    id = 105
    format = _('User {user} restricted.')
    keep = True
    admin_event = True


class ADMIN_VIEWED_LOG(_LOG):
    id = 106
    format = _('Admin {0} viewed activity log for {user}.')
    admin_event = True


class EDIT_RATING(_LOG):
    id = 107
    action_class = 'review'
    format = _('{rating} for {addon} updated.')


class THEME_REVIEW(_LOG):
    id = 108
    action_class = 'review'
    format = _('{addon} reviewed.')
    keep = True


class ADMIN_USER_BANNED(_LOG):
    id = 109
    format = _('User {user} banned.')
    keep = True
    admin_event = True


class ADMIN_USER_PICTURE_DELETED(_LOG):
    id = 110
    format = _('User {user} picture deleted.')
    admin_event = True


class GROUP_USER_ADDED(_LOG):
    id = 120
    action_class = 'access'
    format = _('User {0.name} added to {group}.')
    keep = True
    admin_event = True


class GROUP_USER_REMOVED(_LOG):
    id = 121
    action_class = 'access'
    format = _('User {0.name} removed from {group}.')
    keep = True
    admin_event = True


class ADDON_UNLISTED(_LOG):
    id = 128
    format = _('{addon} unlisted.')
    keep = True


class BETA_SIGNED(_LOG):
    id = 131
    format = _('{file} was signed.')
    keep = True


# Obsolete, we don't care about validation results on beta files.
class BETA_SIGNED_VALIDATION_FAILED(_LOG):
    id = 132
    format = _('{file} was signed.')
    keep = True


class DELETE_ADDON(_LOG):
    id = 133
    action_class = 'delete'
    # L10n: {0} is the add-on GUID.
    format = _('Addon id {0} with GUID {1} has been deleted')
    keep = True


class EXPERIMENT_SIGNED(_LOG):
    id = 134
    format = _('{file} was signed.')
    keep = True


class UNLISTED_SIGNED(_LOG):
    id = 135
    format = _('{file} was signed.')
    keep = True


# Obsolete, we don't care about validation results on unlisted files anymore.
class UNLISTED_SIGNED_VALIDATION_FAILED(_LOG):
    id = 136
    format = _('{file} was signed.')
    keep = True


# Obsolete, we don't care about validation results on unlisted files anymore,
# and the distinction for sideloading add-ons is gone as well.
class UNLISTED_SIDELOAD_SIGNED_VALIDATION_PASSED(_LOG):
    id = 137
    format = _('{file} was signed.')
    keep = True


# Obsolete, we don't care about validation results on unlisted files anymore,
# and the distinction for sideloading add-ons is gone as well.
class UNLISTED_SIDELOAD_SIGNED_VALIDATION_FAILED(_LOG):
    id = 138
    format = _('{file} was signed.')
    keep = True


class PRELIMINARY_ADDON_MIGRATED(_LOG):
    id = 139
    format = _('{addon} migrated from preliminary.')
    keep = True
    review_queue = True


class DEVELOPER_REPLY_VERSION(_LOG):
    id = 140
    format = _('Reply by developer on {addon} {version}.')
    short = _('Developer Reply')
    keep = True
    review_queue = True


class REVIEWER_REPLY_VERSION(_LOG):
    id = 141
    format = _('Reply by reviewer on {addon} {version}.')
    short = _('Reviewer Reply')
    keep = True
    review_queue = True


class APPROVAL_NOTES_CHANGED(_LOG):
    id = 142
    format = _('Approval notes changed for {addon} {version}.')
    short = _('Approval notes changed')
    keep = True
    review_queue = True


class SOURCE_CODE_UPLOADED(_LOG):
    id = 143
    format = _('Source code uploaded for {addon} {version}.')
    short = _('Source code uploaded')
    keep = True
    review_queue = True


class CONFIRM_AUTO_APPROVED(_LOG):
    id = 144
    format = _('Auto-Approval confirmed for {addon} {version}.')
    short = _('Auto-Approval confirmed')
    keep = True
    reviewer_review_action = True
    review_queue = True
    hide_developer = True


class ENABLE_VERSION(_LOG):
    id = 145
    format = _('{addon} {version} re-enabled.')


class DISABLE_VERSION(_LOG):
    id = 146
    format = _('{addon} {version} disabled.')


class APPROVE_CONTENT(_LOG):
    id = 147
    format = _('{addon} {version} content approved.')
    short = _('Content approved')
    keep = True
    reviewer_review_action = True
    review_queue = True
    hide_developer = True


class REJECT_CONTENT(_LOG):
    id = 148
    action_class = 'reject'
    format = _('{addon} {version} content rejected.')
    short = _('Content rejected')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class ADMIN_ALTER_INFO_REQUEST(_LOG):
    id = 149
    format = _('{addon} information request altered or removed by admin.')
    short = _('Information request altered')
    keep = True
    reviewer_review_action = True
    review_queue = True


class DEVELOPER_CLEAR_INFO_REQUEST(_LOG):
    id = 150
    format = _('Information request cleared by developer on {addon} {version}.')
    short = _('Information request removed')
    keep = True
    review_queue = True


class REQUEST_ADMIN_REVIEW_CODE(_LOG):
    id = 151
    format = _('{addon} {version} admin add-on-review requested.')
    short = _('Admin add-on-review requested')
    keep = True
    review_queue = True
    reviewer_review_action = True
    sanitize = REQUEST_SUPER_REVIEW.sanitize


class REQUEST_ADMIN_REVIEW_CONTENT(_LOG):
    id = 152
    format = _('{addon} {version} admin content-review requested.')
    short = _('Admin content-review requested')
    keep = True
    review_queue = True
    reviewer_review_action = True
    sanitize = REQUEST_SUPER_REVIEW.sanitize


class REQUEST_ADMIN_REVIEW_THEME(_LOG):
    id = 153
    format = _('{addon} {version} admin theme-review requested.')
    short = _('Admin theme-review requested')
    keep = True
    review_queue = True
    reviewer_review_action = True
    sanitize = REQUEST_SUPER_REVIEW.sanitize


class CREATE_STATICTHEME_FROM_PERSONA(_LOG):
    id = 154
    action_class = 'add'
    format = _('{addon} was migrated from a lightweight theme.')
    keep = True


class ADMIN_API_KEY_RESET(_LOG):
    id = 155
    format = _('User {user} api key reset.')
    admin_event = True


class BLOCKLIST_BLOCK_ADDED(_LOG):
    id = 156
    keep = True
    action_class = 'add'
    hide_developer = True
    format = _('Block for {0} added to Blocklist.')
    short = _('Block added')


class BLOCKLIST_BLOCK_EDITED(_LOG):
    id = 157
    keep = True
    action_class = 'edit'
    hide_developer = True
    format = _('Block for {0} edited in Blocklist.')
    short = _('Block edited')


class BLOCKLIST_BLOCK_DELETED(_LOG):
    id = 158
    keep = True
    action_class = 'delete'
    hide_developer = True
    format = _('Block for {0} deleted from Blocklist.')
    short = _('Block deleted')


class DENIED_GUID_ADDED(_LOG):
    id = 159
    keep = True
    action_class = 'add'
    hide_developer = True
    format = _('GUID for {addon} added to DeniedGuid.')


class DENIED_GUID_DELETED(_LOG):
    id = 160
    keep = True
    action_class = 'delete'
    hide_developer = True
    format = _('GUID for {addon} removed from DeniedGuid.')


class BLOCKLIST_SIGNOFF(_LOG):
    id = 161
    keep = True
    hide_developer = True
    format = _('Block {1} action for {0} signed off.')
    short = _('Block action signoff')


class ADMIN_USER_SESSION_RESET(_LOG):
    id = 162
    format = _('User {user} session(s) reset.')
    admin_event = True


class THROTTLED(_LOG):
    id = 163
    format = _('User {user} throttled for scope "{0}"')
    admin_event = True


class REJECT_CONTENT_DELAYED(_LOG):
    id = 164
    action_class = 'reject'
    format = _('{addon} {version} content reject scheduled.')
    short = _('Content reject scheduled')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class REJECT_VERSION_DELAYED(_LOG):
    # takes add-on, version, reviewtype
    id = 165
    action_class = 'reject'
    format = _('{addon} {version} reject scheduled.')
    short = _('Rejection scheduled')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class VERSION_RESIGNED(_LOG):
    # takes add-on, version, VersionString
    id = 166
    format = _('{addon} {version} re-signed (previously {0}).')
    short = _('Version re-signed')
    review_queue = True


LOGS = [x for x in vars().values() if isclass(x) and issubclass(x, _LOG) and x != _LOG]
# Make sure there's no duplicate IDs.
assert len(LOGS) == len(set(log.id for log in LOGS))

LOG_BY_ID = dict((log.id, log) for log in LOGS)
LOG = namedtuple('LogTuple', [log.__name__ for log in LOGS])(*[log for log in LOGS])
LOG_ADMINS = [log.id for log in LOGS if hasattr(log, 'admin_event')]
LOG_KEEP = [log.id for log in LOGS if hasattr(log, 'keep')]
LOG_RATING_MODERATION = [log.id for log in LOGS if hasattr(log, 'reviewer_event')]
LOG_REVIEW_QUEUE = [log.id for log in LOGS if hasattr(log, 'review_queue')]
LOG_REVIEWER_REVIEW_ACTION = [
    log.id for log in LOGS if hasattr(log, 'reviewer_review_action')
]

# Is the user emailed the message?
LOG_REVIEW_EMAIL_USER = [log.id for log in LOGS if hasattr(log, 'review_email_user')]
# Logs *not* to show to the developer.
LOG_HIDE_DEVELOPER = [
    log.id
    for log in LOGS
    if (getattr(log, 'hide_developer', False) or log.id in LOG_ADMINS)
]
# Review Queue logs to show to developer (i.e. hiding admin/private)
LOG_REVIEW_QUEUE_DEVELOPER = list(set(LOG_REVIEW_QUEUE) - set(LOG_HIDE_DEVELOPER))
