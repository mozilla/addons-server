from inspect import isclass

from django.conf import settings
from django.core.files.storage import get_storage_class

from celery.datastructures import AttributeDict
from tower import ugettext_lazy as _

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


# TODO(davedash): Log these types when pages are present
class SET_PUBLIC_STATS(_LOG):
    id = 10
    format = _(u'Stats set public for {addon}.')
    keep = True


# TODO(davedash): Log these types when pages are present
class UNSET_PUBLIC_STATS(_LOG):
    id = 11
    format = _(u'{addon} stats set to private.')
    keep = True


class CHANGE_STATUS(_LOG):
    id = 12
    # L10n: {0} is the status
    format = _(u'{addon} status changed to {0}.')
    keep = True


class ADD_PREVIEW(_LOG):
    id = 13
    action_class = 'add'
    format = _(u'Preview added to {addon}.')


class EDIT_PREVIEW(_LOG):
    id = 14
    action_class = 'edit'
    format = _(u'Preview edited for {addon}.')


class DELETE_PREVIEW(_LOG):
    id = 15
    action_class = 'delete'
    format = _(u'Preview deleted from {addon}.')


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


class PRELIMINARY_VERSION(_LOG):
    id = 42
    action_class = 'approve'
    format = _(u'{addon} {version} given preliminary review.')
    short = _(u'Preliminarily approved')
    keep = True
    review_email_user = True
    review_queue = True


class REJECT_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 43
    action_class = 'reject'
    format = _(u'{addon} {version} rejected.')
    short = _(u'Rejected')
    keep = True
    review_email_user = True
    review_queue = True


class RETAIN_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 22
    format = _(u'{addon} {version} retained.')
    short = _(u'Retained')
    keep = True
    review_email_user = True
    review_queue = True


class ESCALATE_VERSION(_LOG):
    # takes add-on, version, reviewtype
    id = 23
    format = _(u'{addon} {version} escalated.')
    short = _(u'Escalated')
    keep = True
    review_email_user = True
    review_queue = True


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


class REQUEST_SUPER_REVIEW(_LOG):
    id = 45
    format = _(u'{addon} {version} super review requested.')
    short = _(u'Super review requested')
    keep = True
    review_queue = True


class COMMENT_VERSION(_LOG):
    id = 49
    format = _(u'Comment on {addon} {version}.')
    short = _(u'Comment')
    keep = True
    review_queue = True
    hide_developer = True


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


class ADD_REVIEW(_LOG):
    id = 29
    action_class = 'review'
    format = _(u'{review} for {addon} written.')


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
    format = _(u'{addon} is now licensed under {0.name}.')


class CHANGE_POLICY(_LOG):
    id = 38
    action_class = 'edit'
    format = _(u'{addon} policy changed.')


class CHANGE_ICON(_LOG):
    id = 39
    action_class = 'edit'
    format = _(u'{addon} icon changed.')


class APPROVE_REVIEW(_LOG):
    id = 40
    action_class = 'approve'
    format = _(u'{review} for {addon} approved.')
    editor_format = _(u'{user} approved {review} for {addon}.')
    keep = True
    editor_event = True


class DELETE_REVIEW(_LOG):
    """Requires review.id and add-on objects."""
    id = 41
    action_class = 'review'
    format = _(u'Review {0} for {addon} deleted.')
    editor_format = _(u'{user} deleted {0} for {addon}.')
    keep = True
    editor_event = True


class MAX_APPVERSION_UPDATED(_LOG):
    id = 46
    format = _(u'Application max version for {version} updated.')


class BULK_VALIDATION_EMAILED(_LOG):
    id = 47
    format = _(u'Authors emailed about compatibility of {version}.')


class CHANGE_PASSWORD(_LOG):
    id = 48
    format = _(u'Password changed.')


class MAKE_PREMIUM(_LOG):
    id = 50
    format = _(u'{addon} changed to premium.')


class PAYPAL_FAILED(_LOG):
    id = 51
    format = _(u'{addon} failed checks with PayPal.')


class MANIFEST_UPDATED(_LOG):
    id = 52
    format = _(u'{addon} manifest updated.')


class APPROVE_VERSION_WAITING(_LOG):
    id = 53
    action_class = 'approve'
    format = _(u'{addon} {version} approved but waiting to be made public.')
    short = _(u'Approved but waiting')
    keep = True
    review_email_user = True
    review_queue = True


class PURCHASE_ADDON(_LOG):
    id = 54
    format = _(u'{addon} purchased.')


class INSTALL_ADDON(_LOG):
    id = 55
    format = _(u'{addon} installed.')


class USER_EDITED(_LOG):
    id = 60
    format = _(u'Account updated.')


class ESCALATION_CLEARED(_LOG):
    id = 66
    format = _(u'Escalation cleared for {addon}.')
    short = _(u'Escalation cleared')
    keep = True
    review_queue = True


class APP_DISABLED(_LOG):
    id = 67
    format = _(u'{addon} disabled.')
    short = _(u'App disabled')
    keep = True
    review_queue = True


class ESCALATED_HIGH_ABUSE(_LOG):
    id = 68
    format = _(u'{addon} escalated because of high number of abuse reports.')
    short = _(u'High Abuse Reports')
    keep = True
    review_queue = True


class REREVIEW_MANIFEST_CHANGE(_LOG):
    id = 70
    format = _(u'{addon} re-reviewed because of manifest change.')
    short = _(u'Manifest Change')
    keep = True
    review_queue = True


class REREVIEW_PREMIUM_TYPE_UPGRADE(_LOG):
    id = 71
    format = _(u'{addon} re-reviewed because app upgraded premium type.')
    short = _(u'Premium Type Upgrade')
    keep = True
    review_queue = True


class REREVIEW_CLEARED(_LOG):
    id = 72
    format = _(u'Re-review cleared for {addon}.')
    short = _(u'Re-review cleared')
    keep = True
    review_queue = True


class ESCALATE_MANUAL(_LOG):
    id = 73
    format = _(u'{addon} escalated by reviewer.')
    short = _(u'Reviewer escalation')
    keep = True
    review_queue = True
# TODO(robhudson): Escalation log for editor escalation..


class VIDEO_ERROR(_LOG):
    id = 74
    format = _(u'Video removed from {addon} because of a problem with '
                'the video. ')
    short = _(u'Video removed')


class REREVIEW_DEVICES_ADDED(_LOG):
    id = 75
    format = _(u'{addon} re-review because of new device(s) added.')
    short = _(u'Device(s) Added')
    keep = True
    review_queue = True


class REVIEW_DEVICE_OVERRIDE(_LOG):
    id = 76
    format = _(u'{addon} device support manually changed by reviewer.')
    short = _(u'Device(s) Changed by Reviewer')
    keep = True
    review_queue = True


class WEBAPP_RESUBMIT(_LOG):
    id = 77
    format = _(u'{addon} resubmitted for review.')
    short = _(u'App Resubmission')
    keep = True
    review_queue = True


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


class EDIT_REVIEW(_LOG):
    id = 107
    action_class = 'review'
    format = _(u'{review} for {addon} updated.')


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


class REVIEW_FEATURES_OVERRIDE(_LOG):
    id = 122
    format = _(u'{addon} minimum requirements manually changed by reviewer.')
    short = _(u'Requirements Changed by Reviewer')
    keep = True
    review_queue = True


class REREVIEW_FEATURES_CHANGED(_LOG):
    id = 123
    format = _(u'{addon} minimum requirements manually changed.')
    short = _(u'Requirements Changed')
    keep = True
    review_queue = True


class CHANGE_VERSION_STATUS(_LOG):
    id = 124
    # L10n: {0} is the status
    format = _(u'{version} status changed to {0}.')
    keep = True


class DELETE_USER_LOOKUP(_LOG):
    id = 125
    # L10n: {0} is the status
    format = _(u'User {0.name} {0.id} deleted via lookup tool.')
    keep = True


class CONTENT_RATING_TO_ADULT(_LOG):
    id = 126
    format = _('{addon} content rating changed to Adult.')
    review_queue = True


class CONTENT_RATING_CHANGED(_LOG):
    id = 127
    format = _('{addon} content rating changed.')


LOGS = [x for x in vars().values()
        if isclass(x) and issubclass(x, _LOG) and x != _LOG]

LOG_BY_ID = dict((l.id, l) for l in LOGS)
LOG = AttributeDict((l.__name__, l) for l in LOGS)
LOG_ADMINS = [l.id for l in LOGS if hasattr(l, 'admin_event')]
LOG_KEEP = [l.id for l in LOGS if hasattr(l, 'keep')]
LOG_EDITORS = [l.id for l in LOGS if hasattr(l, 'editor_event')]
LOG_REVIEW_QUEUE = [l.id for l in LOGS if hasattr(l, 'review_queue')]

# Is the user emailed the message?
LOG_REVIEW_EMAIL_USER = [l.id for l in LOGS if hasattr(l, 'review_email_user')]
# Logs *not* to show to the developer.
LOG_HIDE_DEVELOPER = [l.id for l in LOGS
                           if (getattr(l, 'hide_developer', False)
                               or l.id in LOG_ADMINS)]


def log(action, *args, **kw):
    """
    e.g. amo.log(amo.LOG.CREATE_ADDON, []),
         amo.log(amo.LOG.ADD_FILE_TO_VERSION, file, version)
    """
    from access.models import Group
    from addons.models import Addon
    from amo import get_user, logger_log
    from devhub.models import (ActivityLog, AddonLog, CommentLog, GroupLog,
                               UserLog, VersionLog)
    from users.models import UserProfile
    from versions.models import Version

    user = kw.get('user', get_user())

    if not user:
        logger_log.warning('Activity log called with no user: %s' % action.id)
        return

    al = ActivityLog(user=user, action=action.id)
    al.arguments = args
    if 'details' in kw:
        al.details = kw['details']
    al.save()

    if 'details' in kw and 'comments' in al.details:
        CommentLog(comments=al.details['comments'], activity_log=al).save()

    # TODO(davedash): post-remora this may not be necessary.
    if 'created' in kw:
        al.created = kw['created']
        # Double save necessary since django resets the created date on save.
        al.save()

    for arg in args:
        if isinstance(arg, tuple):
            if arg[0] == Addon:
                AddonLog(addon_id=arg[1], activity_log=al).save()
            elif arg[0] == Version:
                VersionLog(version_id=arg[1], activity_log=al).save()
            elif arg[0] == UserProfile:
                UserLog(user_id=arg[1], activity_log=al).save()
            elif arg[0] == Group:
                GroupLog(group_id=arg[1], activity_log=al).save()
        elif isinstance(arg, Addon):
            AddonLog(addon=arg, activity_log=al).save()
        elif isinstance(arg, Version):
            VersionLog(version=arg, activity_log=al).save()
        elif isinstance(arg, UserProfile):
            # Index by any user who is mentioned as an argument.
            UserLog(activity_log=al, user=arg).save()
        elif isinstance(arg, Group):
            GroupLog(group=arg, activity_log=al).save()

    # Index by every user
    UserLog(activity_log=al, user=user).save()
    return al
