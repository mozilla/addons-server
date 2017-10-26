from olympia import amo


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


def action_allowed(request, permission):
    """
    Determines if the request user has permission to do a certain action.

    `permission` is a tuple constant in constants.permissions.

    Note: relies in user.groups_list, which is cached on the user instance the
    first time it's accessed. See also action_allowed_user().
    """
    return action_allowed_user(request.user, permission)


def action_allowed_user(user, permission):
    """
    Determines if the user has permission to do a certain action.

    `permission` is a tuple constant in constants.permissions.

    Note: relies in user.groups_list, which is cached on the user instance the
    first time it's accessed.
    """
    if not user.is_authenticated():
        return False

    assert permission in amo.permissions.PERMISSIONS_LIST  # constants only.
    return any(
        match_rules(group.rules, permission.app, permission.action)
        for group in user.groups_list)


def submission_allowed(user, parsed_addon_data):
    """Experiments can only be submitted by the people with the right group.

    See bug 1220097.
    """
    return (
        not parsed_addon_data.get('is_experiment', False) or
        action_allowed_user(user, amo.permissions.EXPERIMENTS_SUBMIT))


def check_ownership(request, obj, require_owner=False, require_author=False,
                    ignore_disabled=False, admin=True):
    """
    A convenience function.  Check if request.user has permissions
    for the object.
    """
    if hasattr(obj, 'check_ownership'):
        return obj.check_ownership(request, require_owner=require_owner,
                                   require_author=require_author,
                                   ignore_disabled=ignore_disabled,
                                   admin=admin)
    return False


def check_collection_ownership(request, collection, require_owner=False):
    if not request.user.is_authenticated():
        return False

    if action_allowed(request, amo.permissions.ADMIN):
        return True
    elif action_allowed(request, amo.permissions.COLLECTIONS_EDIT):
        return True
    elif request.user.id == collection.author_id:
        return True
    elif not require_owner:
        return collection.publishable_by(request.user)
    else:
        return False


def check_addon_ownership(request, addon, viewer=False, dev=False,
                          support=False, admin=True, ignore_disabled=False):
    """
    Check request.user's permissions for the addon.

    If user is an admin they can do anything.
    If the add-on is disabled only admins have permission.
    If they're an add-on owner they can do anything.
    dev=True checks that the user has an owner or developer role.
    viewer=True checks that the user has an owner, developer, or viewer role.
    support=True checks that the user has a support role.
    """
    if not request.user.is_authenticated():
        return False
    # Deleted addons can't be edited at all.
    if addon.is_deleted:
        return False
    # Users with 'Addons:Edit' can do anything.
    if admin and action_allowed(request, amo.permissions.ADDONS_EDIT):
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
        roles += (amo.AUTHOR_ROLE_DEV, amo.AUTHOR_ROLE_VIEWER,
                  amo.AUTHOR_ROLE_SUPPORT)
    # Support can do support.
    elif support:
        roles += (amo.AUTHOR_ROLE_SUPPORT,)
    return addon.authors.filter(pk=request.user.pk,
                                addonuser__role__in=roles).exists()


def check_addons_reviewer(request):
    return action_allowed(request, amo.permissions.ADDONS_REVIEW)


def check_unlisted_addons_reviewer(request):
    return action_allowed(request, amo.permissions.ADDONS_REVIEW_UNLISTED)


def check_personas_reviewer(request):
    return action_allowed(request, amo.permissions.THEMES_REVIEW)


def is_reviewer(request, addon):
    """Return True if the user is an addons reviewer, or a personas reviewer
    and the addon is a persona."""
    return (check_addons_reviewer(request) or
            (check_personas_reviewer(request) and addon.is_persona()))
