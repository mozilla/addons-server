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
    """Check if request.user has permissions for the object."""
    if isinstance(obj, Addon):
        return check_addon_ownership(request, obj, require_owner)
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


def check_addon_ownership(request, addon, require_owner=False):
    """Check if request.user has owner permissions for the add-on."""
    if not request.user.is_authenticated():
        return False
    if not require_owner and action_allowed(request, 'Admin', 'EditAnyAddon'):
        return True

    roles = (amo.AUTHOR_ROLE_OWNER, amo.AUTHOR_ROLE_DEV)
    if not require_owner:
        roles += (amo.AUTHOR_ROLE_VIEWER,)

    return bool(addon.authors.filter(addonuser__role__in=roles,
                                     user=request.amo_user))
