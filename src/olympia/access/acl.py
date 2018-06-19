from django.conf import settings

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

    if action_allowed(request, amo.permissions.COLLECTIONS_EDIT):
        return True
    elif request.user.id == collection.author_id:
        return True
    elif not require_owner:
        return (
            collection.pk == settings.COLLECTION_FEATURED_THEMES_ID and
            action_allowed_user(
                request.user, amo.permissions.COLLECTIONS_CONTRIBUTE))
    else:
        return False


def check_addon_ownership(request, addon, dev=False, admin=True,
                          ignore_disabled=False):
    """
    Check request.user's permissions for the addon.

    If user is an admin they can do anything.
    If the add-on is disabled only admins have permission.
    If they're an add-on owner they can do anything.
    dev=True checks that the user has an owner or developer role.
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
    return addon.authors.filter(pk=request.user.pk,
                                addonuser__role__in=roles).exists()


def check_addons_reviewer(request):
    return (
        action_allowed(request, amo.permissions.ADDONS_REVIEW) or
        action_allowed(request, amo.permissions.ADDONS_CONTENT_REVIEW) or
        action_allowed(request, amo.permissions.ADDONS_POST_REVIEW))


def check_unlisted_addons_reviewer(request):
    return action_allowed(request, amo.permissions.ADDONS_REVIEW_UNLISTED)


def check_personas_reviewer(request):
    return action_allowed(request, amo.permissions.THEMES_REVIEW)


def check_static_theme_reviewer(request):
    return action_allowed(request, amo.permissions.STATIC_THEMES_REVIEW)


def is_reviewer(request, addon):
    """Return True if the user is an addons reviewer, or a personas reviewer
    and the addon is a persona."""
    if addon.type == amo.ADDON_PERSONA:
        return check_personas_reviewer(request)
    elif addon.type == amo.ADDON_STATICTHEME:
        return check_static_theme_reviewer(request)
    return check_addons_reviewer(request)


def is_user_any_kind_of_reviewer(user):
    """More lax version of is_reviewer: does not check what kind of reviewer
    the user is, and accepts unlisted reviewers, post reviewers, content
    reviewers, or people with just revierwer tools view access.

    Don't use on anything that would alter add-on data.

    any_reviewer_required() decorator and AllowAnyKindOfReviewer DRF permission
    use this function behind the scenes to guard views that don't change the
    add-on but still need to be restricted to reviewers only.
    """
    allow_access = (
        action_allowed_user(user, amo.permissions.REVIEWER_TOOLS_VIEW) or
        action_allowed_user(user, amo.permissions.ADDONS_REVIEW) or
        action_allowed_user(user, amo.permissions.ADDONS_REVIEW_UNLISTED) or
        action_allowed_user(user, amo.permissions.ADDONS_CONTENT_REVIEW) or
        action_allowed_user(user, amo.permissions.ADDONS_POST_REVIEW) or
        action_allowed_user(user, amo.permissions.THEMES_REVIEW) or
        action_allowed_user(user, amo.permissions.STATIC_THEMES_REVIEW))
    return allow_access
