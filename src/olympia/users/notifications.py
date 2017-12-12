from collections import namedtuple
from inspect import isclass

from django.utils.translation import ugettext_lazy as _


class _NOTIFICATION(object):
    pass


class reply(_NOTIFICATION):
    id = 3
    group = 'user'
    short = 'reply'
    label = _('an add-on developer replies to my review')
    mandatory = False
    default_checked = True


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
    label = _('my add-on\'s compatibility is upgraded successfully')
    mandatory = False
    default_checked = True


class sdk_upgrade_success(_NOTIFICATION):
    id = 6
    group = 'dev'
    short = 'sdk_upgrade_success'
    label = _('my sdk-based add-on is upgraded successfully')
    mandatory = False
    default_checked = True


class new_review(_NOTIFICATION):
    id = 7
    group = 'dev'
    short = 'new_review'
    label = _('someone writes a review of my add-on')
    mandatory = False
    default_checked = True


class announcements(_NOTIFICATION):
    id = 8
    group = 'dev'
    short = 'announcements'
    label = _('stay up-to-date with news and events relevant to add-on '
              'developers (including the about:addons newsletter)')
    mandatory = False
    default_checked = False


class upgrade_fail(_NOTIFICATION):
    id = 9
    group = 'dev'
    short = 'upgrade_fail'
    label = _('my add-on\'s compatibility cannot be upgraded')
    mandatory = True
    default_checked = True


class sdk_upgrade_fail(_NOTIFICATION):
    id = 10
    group = 'dev'
    short = 'sdk_upgrade_fail'
    label = _('my sdk-based add-on cannot be upgraded')
    mandatory = True
    default_checked = True


class reviewer_reviewed(_NOTIFICATION):
    id = 11
    group = 'dev'
    short = 'reviewer_reviewed'
    label = _('my add-on is reviewed by a reviewer')
    mandatory = True
    default_checked = True


class individual_contact(_NOTIFICATION):
    id = 12
    group = 'dev'
    short = 'individual_contact'
    label = _('Mozilla needs to contact me about my individual add-on')
    mandatory = True
    default_checked = True


NOTIFICATION_GROUPS = {'dev': _('Developer'),
                       'user': _('User Notifications')}

NOTIFICATIONS = [x for x in vars().values()
                 if isclass(x) and issubclass(x, _NOTIFICATION) and
                 x != _NOTIFICATION]
NOTIFICATIONS_BY_ID = {l.id: l for l in NOTIFICATIONS}
NOTIFICATIONS_BY_ID_NOT_DEV = {l.id: l for l in NOTIFICATIONS
                               if l.group != 'dev'}

NOTIFICATIONS_BY_SHORT = {l.short: l for l in NOTIFICATIONS}
NOTIFICATION = namedtuple('NotificationTuple',
                          [n.__name__ for n in NOTIFICATIONS]
                          )(*[n for n in NOTIFICATIONS])

NOTIFICATIONS_DEFAULT = [l.id for l in NOTIFICATIONS if l.default_checked]
NOTIFICATIONS_CHOICES = [(l.id, l.label) for l in NOTIFICATIONS]
NOTIFICATIONS_CHOICES_NOT_DEV = [(l.id, l.label) for l in NOTIFICATIONS
                                 if l.group != 'dev']
