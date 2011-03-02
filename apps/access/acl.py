import amo
from addons.models import Addon
from bandwagon.models import Collection


def match_rules(rules, app, action):
    """
    This will match rules found in Group.
    """
    for rule in rules.split(','):
        rule_app, rule_action = rule.split(':')
        if rule_app == '*' or rule_app == app:
            if (rule_action == '*'
                or rule_action == action
                or action == '%'):
                return True
    return False


def action_allowed(request, app, action):
    """
    Determines if a user has permission to do a certain action

    'Admin:%' is true if the user has any of:
    ('Admin:*', 'Admin:%s'%whatever, '*:*',) as rules.
    """

    return any(match_rules(group.rules, app, action)
        for group in getattr(request, 'groups', ()))


def check_ownership(request, obj, require_owner=False):
    """
    A convenience function.  Check if request.user has permissions
    for the object.
    """
    if isinstance(obj, Addon):
        return check_addon_ownership(request, obj, viewer=not require_owner)
    elif isinstance(obj, Collection):
        return check_collection_ownership(request, obj, require_owner)
    else:
        return False


def check_collection_ownership(request, collection, require_owner=False):
    if not request.user.is_authenticated():
        return False

    if action_allowed(request, 'Admin', '%'):
        return True
    elif request.amo_user.id == collection.author_id:
        return True
    elif not require_owner:
        return collection.publishable_by(request.amo_user)
    else:
        return False


def check_addon_ownership(request, addon, viewer=False, dev=False, ignore_disabled=False):
    """
    Check request.amo_user's permissions for the addon.

    If user is an admin they can do anything.
    If the add-on is disabled only admins have permission.
    If they're an add-on owner they can do anything.
    dev=True checks that the user has an owner or developer role.
    viewer=True checks that the user has an owner, developer, or viewer role.
    """
    if not request.user.is_authenticated():
        return False
    # Admins can do anything.
    if action_allowed(request, 'Admin', 'EditAnyAddon'):
        return True
    # Only admins can edit admin-disabled addons.
    if addon.status == amo.STATUS_DISABLED and not ignore_disabled:
        return False
    # Addon owners can do everything else.
    roles = (amo.AUTHOR_ROLE_OWNER,)
    if dev:
        roles += (amo.AUTHOR_ROLE_DEV,)
    # Viewer privs are implied for devs.
    elif viewer:
        roles += (amo.AUTHOR_ROLE_DEV, amo.AUTHOR_ROLE_VIEWER)
    return addon.authors.filter(user=request.amo_user,
                                addonuser__role__in=roles).exists()
