import functools
from rest_framework.permissions import BasePermission

from django.core.exceptions import PermissionDenied

from olympia.amo.decorators import login_required


def match_rules(rules, app, action):
    """
    This will match rules found in Group.
    """
    for rule in rules.split(','):
        rule_app, rule_action = rule.split(':')
        if rule_app == '*' or rule_app == app:
            if rule_action == '*' or rule_action == action or action == '%':
                return True
    return False


class AclPermission(BasePermission):
    """
    Defines what permissions are needed to do a certain action.

    'Admin:%' is true if the user has any of:
    ('Admin:*', 'Admin:%s'%whatever, '*:*',) as rules.

    Note: methods rely on user.groups_list, which is cached on the user
    instance the first time it's accessed.
    """

    def __init__(self, app, action):
        self.app = app
        self.action = action

    def user_has_permission(self, user):
        if not user.is_authenticated():
            return False

        return any(
            match_rules(group.rules, self.app, self.action)
            for group in user.groups_list)

    def has_permission(self, request, view=None):
        # `view` param isn't used
        return self.user_has_permission(request.user)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)

    def __unicode__(self):
        return '%s:%s' % (self.app, self.action)

    def __str__(self):
        return unicode(self).encode('utf-8')

    def __call__(self, *a):
        """
        ignore DRF's nonsensical need to call this object.
        """
        return self

    def decorator(self, f):
        """Makes this Permission into a decorator."""
        @login_required
        @functools.wraps(f)
        def wrapper(request, *args, **kw):
            if self.has_permission(request, None):
                return f(request, *args, **kw)
            raise PermissionDenied
        return wrapper


# Special null rule.
NONE = AclPermission('None', 'None')

# Admin super powers.  Very few users will have this permission (2-3)
ADMIN = AclPermission('Admin', '%')

# Can view admin tools.
ADMINTOOLS = AclPermission('AdminTools', 'View')
# Can view add-on reviewer admin tools.
REVIEWERADMINTOOLS = AclPermission('ReviewerAdminTools', 'View')


# These users gain access to the accounts API to super-create users.
ACCOUNTS_SUPERCREATE = AclPermission('Accounts', 'SuperCreate')

# Can submit an editor review for a listed add-on.
ADDONS_REVIEW = AclPermission('Addons', 'Review')
# Can submit an editor review for an unlisted add-on.
ADDONS_REVIEW_UNLISTED = AclPermission('Addons', 'ReviewUnlisted')
# Can edit the message of the day in the reviewer tools.
ADDONREVIEWERMOTD_EDIT = AclPermission('AddonReviewerMOTD', 'Edit')
# Can submit an editor review for a background theme (persona).
THEMES_REVIEW = AclPermission('Personas', 'Review')

# Can edit the properties of any add-on (pseduo-admin).
ADDONS_EDIT = AclPermission('Addons', 'Edit')

# Can edit all collections.
COLLECTIONS_EDIT = AclPermission('Collections', 'Edit')
