from collections import namedtuple

from celery.datastructures import AttributeDict
from tower import ugettext_lazy as _

__all__ = ('LOG', 'LOG_BY_ID', 'LOG_KEEP',)

_LOG = namedtuple('LOG', 'id format')


class CREATE_ADDON:
    id = 1
    format = _(u'{addon} was created.')
    keep = True


class EDIT_PROPERTIES:
    """ Expects: addon """
    id = 2
    format = _(u'{addon} properties edited.')


class EDIT_DESCRIPTIONS:
    id = 3
    format = _(u'{addon} description edited.')


# TODO(gkoberger): Log this type
class EDIT_CATEGORIES:
    id = 4
    format = _(u'Categories edited for {addon}.')


class ADD_USER_WITH_ROLE:
    id = 5
    format = _(u'{0.name} ({1}) added to {addon}.')
    keep = True


class REMOVE_USER_WITH_ROLE:
    id = 6
    # L10n: {0} is the user being removed, {1} is their role.
    format = _(u'{0.name} ({1}) removed from {addon}.')
    keep = True


class EDIT_CONTRIBUTIONS:
    id = 7
    format = _(u'Contributions for {addon}.')


class USER_DISABLE:
    id = 8
    format = _(u'{addon} set inactive.')
    keep = True


class USER_ENABLE:
    id = 9
    format = _(u'{addon} activated.')
    keep = True


# TODO(davedash): Log these types when pages are present
class SET_PUBLIC_STATS:
    id = 10
    format = _(u'Stats set public for {addon}.')
    keep = True


# TODO(davedash): Log these types when pages are present
class UNSET_PUBLIC_STATS:
    id = 11
    format = _(u'{addon} stats set to private.')
    keep = True


# TODO(gkoberger): Log these types when editing statuses
class CHANGE_STATUS:
    id = 12
    # L10n: {0} is the status
    format = _(u'{addon} status changed to {0}.')
    keep = True


# TODO(gkoberger): Do this in 604152
class ADD_PREVIEW:
    id = 13
    format = _(u'Preview added to {addon}.')


# TODO(gkoberger): Do this in 604152
class EDIT_PREVIEW:
    id = 14
    format = _(u'Preview edited for {addon}.')


# TODO(gkoberger): Do this in 604152
class DELETE_PREVIEW:
    id = 15
    format = _(u'Preview deleted from {addon}.')


class ADD_VERSION:
    id = 16
    format = _(u'{version} added to {addon}.')
    keep = True


class EDIT_VERSION:
    id = 17
    format = _(u'{version} edited for {addon}.')


class DELETE_VERSION:
    id = 18
    # Note, {0} is a string not a version since the version is deleted.
    # L10n: {0} is the version number
    format = _(u'Version {0} deleted from {addon}.')
    keep = True


class ADD_FILE_TO_VERSION:
    id = 19
    format = _(u'File {0.name} added to {version} of {addon}.')


class DELETE_FILE_FROM_VERSION:
    """
    Expecting: addon, filename, version
    Because the file is being deleted, filename and version
    should be strings and not the object.
    """
    id = 20
    format = _(u'File {0} deleted from {version} of {addon}.')


# TODO(davedash): When editor tools exist
class APPROVE_VERSION:
    id = 21
    format = _(u'{addon} {version} approved.')
    keep = True


# TODO(davedash): When editor tools exist
class RETAIN_VERSION:
    id = 22
    format = _(u'{addon} {version} retained.')
    keep = True


# TODO(davedash): When editor tools exist
class ESCALATE_VERSION:
    id = 23
    # L10n: {0.version} is the version of an addon.
    format = _(u'Review escalated for {addon} {version}.')
    keep = True


# TODO(davedash): When editor tools exist
class REQUEST_VERSION:
    id = 24
    # L10n: {0.version} is the version of an addon.
    format = _(u'More information regarding {addon} {version} was requested.')
    keep = True


class ADD_TAG:
    id = 25
    format = _(u'{tag} added to {addon}.')


class REMOVE_TAG:
    id = 26
    format = _(u'{tag} removed from {addon}.')


class ADD_TO_COLLECTION:
    id = 27
    format = _(u'{addon} added to {collection}.')


class REMOVE_FROM_COLLECTION:
    id = 28
    format = _(u'{addon} removed from {collection}.')


class ADD_REVIEW:
    id = 29
    format = _(u'{review} for {addon} written.')


# TODO(davedash): Add these when we do the admin site
class ADD_RECOMMENDED_CATEGORY:
    id = 31
    # L10n: {0} is a category name.
    format = _(u'{addon} featured in {0}.')


class REMOVE_RECOMMENDED_CATEGORY:
    id = 32
    # L10n: {0} is a category name.
    format = _(u'{addon} no longer featured in {0}.')


class ADD_RECOMMENDED:
    id = 33
    format = _(u'{addon} is now featured.')
    keep = True


class REMOVE_RECOMMENDED:
    id = 34
    format = _(u'{addon} is no longer featured.')
    keep = True


class ADD_APPVERSION:
    id = 35
    # L10n: {0} is the application, {1} is the version of the app
    format = _(u'{0} {1} added.')


class CHANGE_USER_WITH_ROLE:
    """ Expects: author.user, role, addon """
    id = 36
    # L10n: {0} is a user, {1} is their role
    format = _(u'{0.name} role changed to {1} for {addon}.')
    keep = True


class CHANGE_LICENSE:
    """ Expects: license, addon """
    id = 37
    format = _(u'{addon} is now licensed under {0.name}.')


class CHANGE_POLICY:
    id = 38
    format = _(u'{addon} policy changed.')


class CHANGE_ICON:
    id = 39
    format = _(u'{addon} icon changed.')


class APPROVE_REVIEW:
    id = 40
    format = _(u'{review} for {addon} approved.')
    editor_format = _(u'{user} approved {review} for {addon}.')
    keep = True
    editor_event = True


class DELETE_REVIEW:
    """Requires review.id and add-on objects."""
    id = 41
    format = _(u'Review {0} deleted.')
    # TODO(davedash): a {more} link will need to go somewhere
    editor_format = _(u'{user} deleted review {0}.')
    keep = True
    editor_event = True


class CUSTOM_TEXT:
    id = 98
    format = '{0}'


class CUSTOM_HTML:
    id = 99
    format = '{0}'


LOGS = (CREATE_ADDON, EDIT_PROPERTIES, EDIT_DESCRIPTIONS, EDIT_CATEGORIES,
        ADD_USER_WITH_ROLE, REMOVE_USER_WITH_ROLE, EDIT_CONTRIBUTIONS,
        USER_DISABLE, USER_ENABLE, SET_PUBLIC_STATS, UNSET_PUBLIC_STATS,
        CHANGE_STATUS, ADD_PREVIEW, EDIT_PREVIEW, DELETE_PREVIEW,
        ADD_VERSION, EDIT_VERSION, DELETE_VERSION, ADD_FILE_TO_VERSION,
        DELETE_FILE_FROM_VERSION, APPROVE_VERSION, RETAIN_VERSION,
        ESCALATE_VERSION, REQUEST_VERSION, ADD_TAG, REMOVE_TAG,
        ADD_TO_COLLECTION, REMOVE_FROM_COLLECTION, ADD_REVIEW,
        ADD_RECOMMENDED_CATEGORY, REMOVE_RECOMMENDED_CATEGORY, ADD_RECOMMENDED,
        REMOVE_RECOMMENDED, ADD_APPVERSION, CUSTOM_TEXT, CUSTOM_HTML,
        CHANGE_USER_WITH_ROLE, CHANGE_LICENSE, CHANGE_POLICY, CHANGE_ICON,
        APPROVE_REVIEW, DELETE_REVIEW,)
LOG_BY_ID = dict((l.id, l) for l in LOGS)
LOG = AttributeDict((l.__name__, l) for l in LOGS)
LOG_KEEP = [l.id for l in LOGS if hasattr(l, 'keep')]
LOG_EDITORS = [l.id for l in LOGS if hasattr(l, 'editor_event')]


def log(action, *args, **kw):
    """
    e.g. amo.log(amo.LOG.CREATE_ADDON, []),
         amo.log(amo.LOG.ADD_FILE_TO_VERSION, file, version)
    """
    from devhub.models import ActivityLog, AddonLog, UserLog
    from addons.models import Addon
    from users.models import UserProfile
    from amo import get_user, logger_log

    user = kw.get('user', get_user())

    if not user:
        logger_log.warning('Activity log called with no user: %s' % action.id)
        return

    al = ActivityLog(user=user, action=action.id)
    al.arguments = args
    if 'details' in kw:
        al.details = kw['details']
    al.save()

    # TODO(davedash): post-remora this may not be necessary.
    if 'created' in kw:
        al.created = kw['created']
        # Double save necessary since django resets the created date on save.
        al.save()

    for arg in args:
        if isinstance(arg, tuple):
            if arg[0] == Addon:
                AddonLog(addon_id=arg[1], activity_log=al).save()
            elif arg[0] == UserProfile:
                AddonLog(user_id=arg[1], activity_log=al).save()
        if isinstance(arg, Addon):
            AddonLog(addon=arg, activity_log=al).save()
        elif isinstance(arg, UserProfile):
            # Index by any user who is mentioned as an argument.
            UserLog(activity_log=al, user=arg).save()

    # Index by every user
    UserLog(activity_log=al, user=user).save()
    return al
