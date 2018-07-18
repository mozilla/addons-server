from collections import namedtuple

from django.utils.translation import ugettext_lazy as _


Notification = namedtuple(
    'Notification',
    ('id', 'group', 'short', 'label', 'mandatory', 'default_checked'),
)

RemoteNotification = namedtuple(
    'RemoteNotification',
    (
        'id',
        'group',
        'short',
        'label',
        'mandatory',
        'default_checked',
        'basket_newsletter_id',
    ),
)

reply = Notification(
    id=3,
    group='user',
    short='reply',
    label=_('an add-on developer replies to my review'),
    mandatory=False,
    default_checked=True,
)

new_features = Notification(
    id=4,
    group='user',
    short='new_features',
    label=_('new add-ons or Firefox features are available'),
    mandatory=False,
    default_checked=True,
)

upgrade_success = Notification(
    id=5,
    group='dev',
    short='upgrade_success',
    label=_('my add-on\'s compatibility is upgraded successfully'),
    mandatory=False,
    default_checked=True,
)

sdk_upgrade_success = Notification(
    id=6,
    group='dev',
    short='sdk_upgrade_success',
    label=_('my sdk-based add-on is upgraded successfully'),
    mandatory=False,
    default_checked=True,
)

new_review = Notification(
    id=7,
    group='dev',
    short='new_review',
    label=_('someone writes a review of my add-on'),
    mandatory=False,
    default_checked=True,
)

# This is the about-addons newsletter.
#
# The newsletter is managed in Salesforce and syncronized via
# basket. It's not used in addons-server except for the user
# profile forms.
announcements = RemoteNotification(
    id=8,
    group='dev',
    short='announcements',
    label=_(
        'stay up-to-date with news and events relevant to add-on '
        'developers (including the about:addons newsletter)'
    ),
    mandatory=False,
    default_checked=False,
    basket_newsletter_id='about-addons',
)

upgrade_fail = Notification(
    id=9,
    group='dev',
    short='upgrade_fail',
    label=_('my add-on\'s compatibility cannot be upgraded'),
    mandatory=True,
    default_checked=True,
)

sdk_upgrade_fail = Notification(
    id=10,
    group='dev',
    short='sdk_upgrade_fail',
    label=_('my sdk-based add-on cannot be upgraded'),
    mandatory=True,
    default_checked=True,
)

reviewer_reviewed = Notification(
    id=11,
    group='dev',
    short='reviewer_reviewed',
    label=_('my add-on is reviewed by a reviewer'),
    mandatory=True,
    default_checked=True,
)

individual_contact = Notification(
    id=12,
    group='dev',
    short='individual_contact',
    label=_('Mozilla needs to contact me about my individual add-on'),
    mandatory=True,
    default_checked=True,
)


NOTIFICATION_GROUPS = {'dev': _('Developer'), 'user': _('User Notifications')}

AMO_NOTIFICATIONS = [
    reply,
    new_features,
    upgrade_success,
    sdk_upgrade_success,
    new_review,
    upgrade_fail,
    sdk_upgrade_fail,
    reviewer_reviewed,
    individual_contact,
]

REMOTE_NOTIFICATIONS = [announcements]

NOTIFICATIONS_COMBINED = AMO_NOTIFICATIONS + REMOTE_NOTIFICATIONS

NOTIFICATIONS_BY_ID = {l.id: l for l in NOTIFICATIONS_COMBINED}
NOTIFICATIONS_BY_ID_NOT_DEV = {
    l.id: l for l in NOTIFICATIONS_COMBINED if l.group != 'dev'
}

REMOTE_NOTIFICATIONS_BY_BASKET_ID = {
    l.basket_newsletter_id: l for l in REMOTE_NOTIFICATIONS
}

NOTIFICATIONS_BY_SHORT = {l.short: l for l in NOTIFICATIONS_COMBINED}
NOTIFICATIONS_DEFAULT = [
    l.id for l in NOTIFICATIONS_COMBINED if l.default_checked
]
