# The absolute import feature is required so that we get the root celery
# module rather than `amo.celery`.
from __future__ import absolute_import

from collections import namedtuple
from inspect import isclass

from django.utils.translation import ugettext_lazy as _


__all__ = ('LOG', 'LOG_BY_ID', 'LOG_KEEP',)


class _LOG(object):
    action_class = None


class CREATE_ADDON(_LOG):
    id = 1
    action_class = 'add'
    format = _(u'{addon} was created.')
    keep = True


class EDIT_PROPERTIES(_LOG):
    """ Expects: addon """
    id = 2
    action_class = 'edit'
    format = _(u'{addon} properties edited.')


class EDIT_DESCRIPTIONS(_LOG):
    id = 3
    action_class = 'edit'
    format = _(u'{addon} description edited.')


class EDIT_CATEGORIES(_LOG):
    id = 4
    action_class = 'edit'
    format = _(u'Categories edited for {addon}.')


class ADD_USER_WITH_ROLE(_LOG):
    id = 5
    action_class = 'add'
    format = _(u'{0.name} ({1}) added to {addon}.')
    keep = True


class REMOVE_USER_WITH_ROLE(_LOG):
    id = 6
    action_class = 'delete'
    # L10n: {0} is the user being removed, {1} is their role.
    format = _(u'{0.name} ({1}) removed from {addon}.')
    keep = True


class EDIT_CONTRIBUTIONS(_LOG):
    id = 7
    action_class = 'edit'
    format = _(u'Contributions for {addon}.')


class USER_DISABLE(_LOG):
    id = 8
    format = _(u'{addon} disabled.')
    keep = True


class USER_ENABLE(_LOG):
    id = 9
    format = _(u'{addon} enabled.')
    keep = True


class CHANGE_STATUS(_LOG):
    id = 12
    # L10n: {status} is the status
    format = _(u'{addon} status changed to {status}.')
    keep = True


class ADD_VERSION(_LOG):
    id = 16
    action_class = 'add'
    format = _(u'{version} added to {addon}.')
    keep = True


class EDIT_VERSION(_LOG):
    id = 17
    action_class = 'edit'
    format = _(u'{version} edited for {addon}.')


class DELETE_VERSION(_LOG):
    id = 18
    action_class = 'delete'
    # Note, {0} is a string not a version since the version is deleted.
    # L10n: {0} is the version number
    format = _(u'Version {0} deleted from {addon}.')
    keep = True


class ADD_FILE_TO_VERSION(_LOG):
    id = 19
    action_class = 'add'
    format = _(u'File {0.name} added to {version} of {addon}.')


class DELETE_FILE_FROM_VERSION(_LOG):
    """
    Expecting: addon, filename, version
    Because the file is being deleted, filename and version
    should be strings and not the object.
    """
    id = 20
    action_class = 'delete'
    format = _(u'File {0} deleted from {version} of {addon}.')


class APPROVE_VERSION(_LOG):
    id = 21
    action_class = 'approve'
    format = _(u'{addon} {version} approved.')
    short = _(u'Approved')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class PRELIMINARY_VERSION(_LOG):
    id = 42
    action_class = 'approve'
    format = _(u'{addon} {version} given preliminary review.')
    short = _(u'Preliminarily approved')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class REJECT_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 43
    action_class = 'reject'
    format = _(u'{addon} {version} rejected.')
    short = _(u'Rejected')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class RETAIN_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 22
    format = _(u'{addon} {version} retained.')
    short = _(u'Retained')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class ESCALATE_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 23
    format = _(u'{addon} {version} escalated.')
    short = _(u'Super review requested')
    keep = True
    review_email_user = True
    review_queue = True
    hide_developer = True


class REQUEST_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 24
    format = _(u'{addon} {version} review requested.')
    short = _(u'Review requested')
    keep = True
    review_email_user = True
    review_queue = True


class REQUEST_INFORMATION(_LOG):
    id = 44
    format = _(u'{addon} {version} more information requested.')
    short = _(u'More information requested')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class REQUEST_SUPER_REVIEW(_LOG):
    id = 45
    format = _(u'{addon} {version} super review requested.')
    short = _(u'Super review requested')
    keep = True
    review_queue = True
    sanitize = _(u'The addon has been flagged for Admin Review.  It\'s still '
                 u'in our review queue, but it will need to be checked by one '
                 u'of our admin reviewers. The review might take longer than '
                 u'usual.')
    reviewer_review_action = True


class COMMENT_VERSION(_LOG):
    id = 49
    format = _(u'Comment on {addon} {version}.')
    short = _(u'Commented')
    keep = True
    review_queue = True
    hide_developer = True
    reviewer_review_action = True


class ADD_TAG(_LOG):
    id = 25
    action_class = 'tag'
    format = _(u'{tag} added to {addon}.')


class REMOVE_TAG(_LOG):
    id = 26
    action_class = 'tag'
    format = _(u'{tag} removed from {addon}.')


class ADD_TO_COLLECTION(_LOG):
    id = 27
    action_class = 'collection'
    format = _(u'{addon} added to {collection}.')


class REMOVE_FROM_COLLECTION(_LOG):
    id = 28
    action_class = 'collection'
    format = _(u'{addon} removed from {collection}.')


class ADD_RATING(_LOG):
    id = 29
    action_class = 'review'
    format = _(u'{rating} for {addon} written.')


# TODO(davedash): Add these when we do the admin site
class ADD_RECOMMENDED_CATEGORY(_LOG):
    id = 31
    action_class = 'edit'
    # L10n: {0} is a category name.
    format = _(u'{addon} featured in {0}.')


class REMOVE_RECOMMENDED_CATEGORY(_LOG):
    id = 32
    action_class = 'edit'
    # L10n: {0} is a category name.
    format = _(u'{addon} no longer featured in {0}.')


class ADD_RECOMMENDED(_LOG):
    id = 33
    format = _(u'{addon} is now featured.')
    keep = True


class REMOVE_RECOMMENDED(_LOG):
    id = 34
    format = _(u'{addon} is no longer featured.')
    keep = True


class ADD_APPVERSION(_LOG):
    id = 35
    action_class = 'add'
    # L10n: {0} is the application, {1} is the version of the app
    format = _(u'{0} {1} added.')


class CHANGE_USER_WITH_ROLE(_LOG):
    """ Expects: author.user, role, addon """
    id = 36
    # L10n: {0} is a user, {1} is their role
    format = _(u'{0.name} role changed to {1} for {addon}.')
    keep = True


class CHANGE_LICENSE(_LOG):
    """ Expects: license, addon """
    id = 37
    action_class = 'edit'
    format = _(u'{addon} is now licensed under {0}.')


class CHANGE_POLICY(_LOG):
    id = 38
    action_class = 'edit'
    format = _(u'{addon} policy changed.')


class CHANGE_ICON(_LOG):
    id = 39
    action_class = 'edit'
    format = _(u'{addon} icon changed.')


class APPROVE_RATING(_LOG):
    id = 40
    action_class = 'approve'
    format = _(u'{rating} for {addon} approved.')
    reviewer_format = _(u'{user} approved {rating} for {addon}.')
    keep = True
    reviewer_event = True


class DELETE_RATING(_LOG):
    """Requires rating.id and add-on objects."""
    id = 41
    action_class = 'review'
    format = _(u'Review {rating} for {addon} deleted.')
    reviewer_format = _(u'{user} deleted {rating} for {addon}.')
    keep = True
    reviewer_event = True


class MAX_APPVERSION_UPDATED(_LOG):
    id = 46
    format = _(u'Application max version for {version} updated.')


class BULK_VALIDATION_EMAILED(_LOG):
    id = 47
    format = _(u'Authors emailed about compatibility of {version}.')


class BULK_VALIDATION_USER_EMAILED(_LOG):
    id = 130
    format = _(u'Email sent to Author about add-on compatibility.')


class CHANGE_PASSWORD(_LOG):
    id = 48
    format = _(u'Password changed.')


class APPROVE_VERSION_WAITING(_LOG):
    id = 53
    action_class = 'approve'
    format = _(u'{addon} {version} approved but waiting to be made public.')
    short = _(u'Approved but waiting')
    keep = True
    review_email_user = True
    review_queue = True


class USER_EDITED(_LOG):
    id = 60
    format = _(u'Account updated.')


class CUSTOM_TEXT(_LOG):
    id = 98
    format = '{0}'


class CUSTOM_HTML(_LOG):
    id = 99
    format = '{0}'


class OBJECT_ADDED(_LOG):
    id = 100
    format = _(u'Created: {0}.')
    admin_event = True


class OBJECT_EDITED(_LOG):
    id = 101
    format = _(u'Edited field: {2} set to: {0}.')
    admin_event = True


class OBJECT_DELETED(_LOG):
    id = 102
    format = _(u'Deleted: {1}.')
    admin_event = True


class ADMIN_USER_EDITED(_LOG):
    id = 103
    format = _(u'User {user} edited, reason: {1}')
    admin_event = True


class ADMIN_USER_ANONYMIZED(_LOG):
    id = 104
    format = _(u'User {user} anonymized.')
    admin_event = True


class ADMIN_USER_RESTRICTED(_LOG):
    id = 105
    format = _(u'User {user} restricted.')
    admin_event = True


class ADMIN_VIEWED_LOG(_LOG):
    id = 106
    format = _(u'Admin {0} viewed activity log for {user}.')
    admin_event = True


class EDIT_RATING(_LOG):
    id = 107
    action_class = 'review'
    format = _(u'{rating} for {addon} updated.')


class THEME_REVIEW(_LOG):
    id = 108
    action_class = 'review'
    format = _(u'{addon} reviewed.')


class GROUP_USER_ADDED(_LOG):
    id = 120
    action_class = 'access'
    format = _(u'User {0.name} added to {group}.')
    keep = True
    admin_event = True


class GROUP_USER_REMOVED(_LOG):
    id = 121
    action_class = 'access'
    format = _(u'User {0.name} removed from {group}.')
    keep = True
    admin_event = True


class ADDON_UNLISTED(_LOG):
    id = 128
    format = _(u'{addon} unlisted.')
    keep = True


class BETA_SIGNED(_LOG):
    id = 131
    format = _(u'{file} was signed.')
    keep = True


# Obsolete, we don't care about validation results on beta files.
class BETA_SIGNED_VALIDATION_FAILED(_LOG):
    id = 132
    format = _(u'{file} was signed.')
    keep = True


class DELETE_ADDON(_LOG):
    id = 133
    action_class = 'delete'
    # L10n: {0} is the add-on GUID.
    format = _(u'Addon id {0} with GUID {1} has been deleted')
    keep = True


class EXPERIMENT_SIGNED(_LOG):
    id = 134
    format = _(u'{file} was signed.')
    keep = True


class UNLISTED_SIGNED(_LOG):
    id = 135
    format = _(u'{file} was signed.')
    keep = True


# Obsolete, we don't care about validation results on unlisted files anymore.
class UNLISTED_SIGNED_VALIDATION_FAILED(_LOG):
    id = 136
    format = _(u'{file} was signed.')
    keep = True


# Obsolete, we don't care about validation results on unlisted files anymore,
# and the distinction for sideloading add-ons is gone as well.
class UNLISTED_SIDELOAD_SIGNED_VALIDATION_PASSED(_LOG):
    id = 137
    format = _(u'{file} was signed.')
    keep = True


# Obsolete, we don't care about validation results on unlisted files anymore,
# and the distinction for sideloading add-ons is gone as well.
class UNLISTED_SIDELOAD_SIGNED_VALIDATION_FAILED(_LOG):
    id = 138
    format = _(u'{file} was signed.')
    keep = True


class PRELIMINARY_ADDON_MIGRATED(_LOG):
    id = 139
    format = _(u'{addon} migrated from preliminary.')
    keep = True
    review_queue = True


class DEVELOPER_REPLY_VERSION(_LOG):
    id = 140
    format = _(u'Reply by developer on {addon} {version}.')
    short = _(u'Developer Reply')
    keep = True
    review_queue = True


class REVIEWER_REPLY_VERSION(_LOG):
    id = 141
    format = _(u'Reply by reviewer on {addon} {version}.')
    short = _(u'Reviewer Reply')
    keep = True
    review_queue = True


class APPROVAL_NOTES_CHANGED(_LOG):
    id = 142
    format = _(u'Approval notes changed for {addon} {version}.')
    short = _(u'Approval notes changed')
    keep = True
    review_queue = True


class SOURCE_CODE_UPLOADED(_LOG):
    id = 143
    format = _(u'Source code uploaded for {addon} {version}.')
    short = _(u'Source code uploaded')
    keep = True
    review_queue = True


class CONFIRM_AUTO_APPROVED(_LOG):
    id = 144
    format = _(u'Auto-Approval confirmed for {addon} {version}.')
    short = _(u'Auto-Approval confirmed')
    keep = True
    reviewer_review_action = True
    review_queue = True
    hide_developer = True


class ENABLE_VERSION(_LOG):
    id = 145
    format = _(u'{addon} {version} re-enabled.')


class DISABLE_VERSION(_LOG):
    id = 146
    format = _(u'{addon} {version} disabled.')


class APPROVE_CONTENT(_LOG):
    id = 147
    format = _(u'{addon} {version} content approved.')
    short = _(u'Content approved')
    keep = True
    reviewer_review_action = True
    review_queue = True
    hide_developer = True


class REJECT_CONTENT(_LOG):
    id = 148
    action_class = 'reject'
    format = _(u'{addon} {version} content rejected.')
    short = _(u'Content rejected')
    keep = True
    review_email_user = True
    review_queue = True
    reviewer_review_action = True


class ADMIN_ALTER_INFO_REQUEST(_LOG):
    id = 149
    format = _(u'{addon} information request altered or removed by admin.')
    short = _(u'Information request altered')
    keep = True
    reviewer_review_action = True
    review_queue = True


class DEVELOPER_CLEAR_INFO_REQUEST(_LOG):
    id = 150
    format = _(u'Information request cleared by developer on '
               u'{addon} {version}.')
    short = _(u'Information request removed')
    keep = True
    review_queue = True


LOGS = [x for x in vars().values()
        if isclass(x) and issubclass(x, _LOG) and x != _LOG]
# Make sure there's no duplicate IDs.
assert len(LOGS) == len(set(log.id for log in LOGS))

LOG_BY_ID = dict((l.id, l) for l in LOGS)
LOG = namedtuple('LogTuple', [l.__name__ for l in LOGS])(*[l for l in LOGS])
LOG_ADMINS = [l.id for l in LOGS if hasattr(l, 'admin_event')]
LOG_KEEP = [l.id for l in LOGS if hasattr(l, 'keep')]
LOG_RATING_MODERATION = [l.id for l in LOGS if hasattr(l, 'reviewer_event')]
LOG_REVIEW_QUEUE = [l.id for l in LOGS if hasattr(l, 'review_queue')]
LOG_REVIEWER_REVIEW_ACTION = [
    l.id for l in LOGS if hasattr(l, 'reviewer_review_action')]

# Is the user emailed the message?
LOG_REVIEW_EMAIL_USER = [l.id for l in LOGS if hasattr(l, 'review_email_user')]
# Logs *not* to show to the developer.
LOG_HIDE_DEVELOPER = [l.id for l in LOGS
                      if (getattr(l, 'hide_developer', False) or
                          l.id in LOG_ADMINS)]
# Review Queue logs to show to developer (i.e. hiding admin/private)
LOG_REVIEW_QUEUE_DEVELOPER = list(set(LOG_REVIEW_QUEUE) -
                                  set(LOG_HIDE_DEVELOPER))
