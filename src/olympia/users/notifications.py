from inspect import isclass

from celery.datastructures import AttributeDict
from django.utils.translation import ugettext_lazy as _


class _NOTIFICATION(object):
    pass


class thanks(_NOTIFICATION):
    id = 2
    group = 'user'
    short = 'dev_thanks'
    label = _('an add-on developer thanks me for a contribution')
    mandatory = False
    default_checked = True


class reply(_NOTIFICATION):
    id = 3
    group = 'user'
    short = 'reply'
    label = _('an add-on developer replies to my review')
    mandatory = False
    default_checked = True


class app_reply(reply):
    app = True
    short = 'app_reply'
    label = _('an app developer replies to my review')


class new_features(_NOTIFICATION):
    id = 4
    group = 'user'
    short = 'new_features'
    label = _('new add-ons or Firefox features are available')
    mandatory = False
    default_checked = True


class upgrade_success(_NOTIFICATION):
    id = 5
    group = 'dev'
    short = 'upgrade_success'
    label = _("my add-on's compatibility is upgraded successfully")
    mandatory = False
    default_checked = True


class sdk_upgrade_success(_NOTIFICATION):
    id = 6
    group = 'dev'
    short = 'sdk_upgrade_success'
    label = _("my sdk-based add-on is upgraded successfully")
    mandatory = False
    default_checked = True


class new_review(_NOTIFICATION):
    id = 7
    group = 'dev'
    short = 'new_review'
    label = _("someone writes a review of my add-on")
    mandatory = False
    default_checked = True


class app_new_review(new_review):
    app = True
    short = 'app_new_review'
    label = _('someone writes a review of my app')


class announcements(_NOTIFICATION):
    id = 8
    group = 'dev'
    short = 'announcements'
    label = _("add-on contests or events are announced")
    mandatory = False
    default_checked = True


class upgrade_fail(_NOTIFICATION):
    id = 9
    group = 'dev'
    short = 'upgrade_fail'
    label = _("my add-on's compatibility cannot be upgraded")
    mandatory = True
    default_checked = True


class sdk_upgrade_fail(_NOTIFICATION):
    id = 10
    group = 'dev'
    short = 'sdk_upgrade_fail'
    label = _("my sdk-based add-on cannot be upgraded")
    mandatory = True
    default_checked = True


class editor_reviewed(_NOTIFICATION):
    id = 11
    group = 'dev'
    short = 'editor_reviewed'
    label = _("my add-on is reviewed by an editor")
    mandatory = True
    default_checked = True


class individual_contact(_NOTIFICATION):
    id = 12
    group = 'dev'
    short = 'individual_contact'
    label = _("Mozilla needs to contact me about my individual add-on")
    mandatory = True
    default_checked = True


class app_reviewed(editor_reviewed):
    app = True
    # Note: This is super ambiguous language if we say "reviewer."
    short = 'app_reviewed'
    label = _('my app is reviewed by an editor')


class app_individual_contact(individual_contact):
    app = True
    short = 'app_individual_contact'
    label = _('Mozilla needs to contact me about my individual app')


class app_surveys(_NOTIFICATION):
    id = 13
    group = 'dev'
    short = 'app_surveys'
    label = _('Mozilla wants to contact me about relevant App Developer news '
              'and surveys')
    mandatory = False
    default_checked = False
    app = True


class app_regions(_NOTIFICATION):
    id = 14
    group = 'dev'
    short = 'app_regions'
    label = _('Mozilla wants to contact me about new regions added to the '
              'Marketplace')
    mandatory = False
    default_checked = True
    app = True


NOTIFICATION_GROUPS = {'dev': _('Developer'),
                       'user': _('User Notifications')}

APP_NOTIFICATIONS = [app_reply, app_new_review, app_reviewed,
                     app_individual_contact, app_surveys, app_regions]
APP_NOTIFICATIONS_BY_ID = dict((l.id, l) for l in APP_NOTIFICATIONS)
APP_NOTIFICATIONS_DEFAULT = [l.id for l in APP_NOTIFICATIONS]
APP_NOTIFICATIONS_CHOICES = [(l.id, l.label) for l in APP_NOTIFICATIONS]
APP_NOTIFICATIONS_CHOICES_NOT_DEV = [(l.id, l.label) for l in APP_NOTIFICATIONS
                                     if l.group != 'dev']

NOTIFICATIONS = [x for x in vars().values()
                 if isclass(x) and issubclass(x, _NOTIFICATION) and
                 x != _NOTIFICATION and not getattr(x, 'app', False)]
NOTIFICATIONS_BY_ID = dict((l.id, l) for l in NOTIFICATIONS)

ALL_NOTIFICATIONS_BY_ID = dict((l.id, l) for l in
                               NOTIFICATIONS + APP_NOTIFICATIONS)

NOTIFICATIONS_BY_SHORT = dict((l.short, l) for l in
                              NOTIFICATIONS + APP_NOTIFICATIONS)
NOTIFICATION = AttributeDict((l.__name__, l) for l in NOTIFICATIONS)

NOTIFICATIONS_DEFAULT = [l.id for l in NOTIFICATIONS if l.default_checked]
NOTIFICATIONS_CHOICES = [(l.id, l.label) for l in NOTIFICATIONS]
NOTIFICATIONS_CHOICES_NOT_DEV = [(l.id, l.label) for l in NOTIFICATIONS
                                 if l.group != 'dev']
