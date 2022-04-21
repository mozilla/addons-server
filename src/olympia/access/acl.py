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


def action_allowed(request_or_user, permission):
    """
    Determines if the request user has permission to do a certain action.

    `permission` is a tuple constant in constants.permissions.

    Note: relies in user.groups_list, which is cached on the user instance the
    first time it's accessed. See also action_allowed_user().
    """
    if hasattr(request_or_user, 'user'):
        user = request_or_user.user
    else:
        user = request_or_user
    return action_allowed_user(user, permission)


def action_allowed_user(user, permission):
    """
    Determines if the user has permission to do a certain action.

    `permission` is a tuple constant in constants.permissions.

    Note: relies in user.groups_list, which is cached on the user instance the
    first time it's accessed.
    """
    if user is None or not user.is_authenticated:
        return False

    assert permission in amo.permissions.PERMISSIONS_LIST  # constants only.
    return any(
        match_rules(group.rules, permission.app, permission.action)
        for group in user.groups_list
    )


def experiments_submission_allowed(user, parsed_addon_data):
    """Experiments can only be submitted by the people with the right
    permission.

    See bug 1220097.
    """
    return not parsed_addon_data.get('is_experiment', False) or action_allowed_user(
        user, amo.permissions.EXPERIMENTS_SUBMIT
    )


def langpack_submission_allowed(user, parsed_addon_data):
    """Language packs can only be submitted by people with the right
    permission.

    See https://github.com/mozilla/addons-server/issues/11788 and
    https://github.com/mozilla/addons-server/issues/11793
    """
    return not parsed_addon_data.get('type') == amo.ADDON_LPAPP or action_allowed_user(
        user, amo.permissions.LANGPACK_SUBMIT
    )


def reserved_guid_addon_submission_allowed(user, parsed_addon_data):
    """Add-ons with a guid ending with reserved suffixes can only be submitted
    by people with the right permission.
    """
    guid = parsed_addon_data.get('guid') or ''
    return not guid.lower().endswith(amo.RESERVED_ADDON_GUIDS) or action_allowed_user(
        user, amo.permissions.SYSTEM_ADDON_SUBMIT
    )


def mozilla_signed_extension_submission_allowed(user, parsed_addon_data):
    """Add-ons already signed with mozilla internal certificate can only be
    submitted by people with the right permission.
    """
    return not parsed_addon_data.get(
        'is_mozilla_signed_extension'
    ) or action_allowed_user(user, amo.permissions.SYSTEM_ADDON_SUBMIT)


def site_permission_addons_submission_allowed(user, parsed_addon_data):
    """Site Permission Add-ons can only be submitted by users with a specific
    permission or the task user."""
    return (
        not parsed_addon_data.get('type') == amo.ADDON_SITE_PERMISSION
        or action_allowed_user(user, amo.permissions.ADDONS_SUBMIT_SITE_PERMISSION)
        or (user and user.pk == settings.TASK_USER_ID)
    )


def check_addon_ownership(
    request,
    addon,
    allow_developer=False,
    allow_addons_edit_permission=True,
    allow_mozilla_disabled_addon=False,
    allow_site_permission=False,
):
    """
    Check that request.user is the owner of the add-on.

    Will always return False for deleted add-ons.

    By default, this function will:
    - return False for mozilla disabled add-ons. Can be bypassed with
      allow_mozilla_disabled_addon=True.
    - return False if the author is just a developer and not an owner. Can be
      bypassed with allow_developer=True.
    - return False for site permission add-ons regardless of authorship. Can be
      bypassed with allow_site_permission=True, in which case regular authorship checks
      apply.
    - return False for non authors. Can be bypassed with
      allow_addons_edit_permission=True and the user has the Addons:Edit
      permission. This has precedence over all other checks.
    """
    if not request.user.is_authenticated:
        return False
    # Deleted addons can't be edited at all.
    if addon.is_deleted:
        return False
    # Users with 'Addons:Edit' can do anything.
    if allow_addons_edit_permission and action_allowed(
        request, amo.permissions.ADDONS_EDIT
    ):
        return True
    # Only admins can edit admin-disabled addons.
    if addon.status == amo.STATUS_DISABLED and not allow_mozilla_disabled_addon:
        return False
    # Site permission add-ons can't be edited by default.
    if addon.type == amo.ADDON_SITE_PERMISSION and not allow_site_permission:
        return False
    # Addon owners can do everything else.
    roles = (amo.AUTHOR_ROLE_OWNER,)
    if allow_developer:
        roles += (amo.AUTHOR_ROLE_DEV,)

    return addon.addonuser_set.filter(user=request.user, role__in=roles).exists()


def check_listed_addons_reviewer(request_or_user, allow_content_reviewers=True):
    permissions = [
        amo.permissions.ADDONS_REVIEW,
        amo.permissions.ADDONS_RECOMMENDED_REVIEW,
    ]
    if allow_content_reviewers:
        permissions.append(amo.permissions.ADDONS_CONTENT_REVIEW)
    allow_access = any(action_allowed(request_or_user, perm) for perm in permissions)
    return allow_access


def check_listed_addons_viewer_or_reviewer(
    request_or_user, allow_content_reviewers=True
):
    return action_allowed(
        request_or_user, amo.permissions.REVIEWER_TOOLS_VIEW
    ) or check_listed_addons_reviewer(request_or_user, allow_content_reviewers)


def check_unlisted_addons_reviewer(request_or_user):
    return action_allowed(request_or_user, amo.permissions.ADDONS_REVIEW_UNLISTED)


def check_unlisted_addons_viewer_or_reviewer(request_or_user):
    return action_allowed(
        request_or_user, amo.permissions.REVIEWER_TOOLS_UNLISTED_VIEW
    ) or check_unlisted_addons_reviewer(request_or_user)


def check_static_theme_reviewer(request_or_user):
    return action_allowed(request_or_user, amo.permissions.STATIC_THEMES_REVIEW)


def is_reviewer(request_or_user, addon, allow_content_reviewers=True):
    """Return True if the user is an addons reviewer, or a theme reviewer
    and the addon is a theme.

    If allow_content_reviewers is passed and False (defaults to True), then
    having content review permission is not enough to be considered an addons
    reviewer.
    """
    if addon.type == amo.ADDON_STATICTHEME:
        return check_static_theme_reviewer(request_or_user)
    return check_listed_addons_reviewer(
        request_or_user, allow_content_reviewers=allow_content_reviewers
    )


def is_user_any_kind_of_reviewer(user, allow_viewers=False):
    """More lax version of is_reviewer: does not check what kind of reviewer
    the user is, and accepts unlisted reviewers, post reviewers, content
    reviewers. If allow_viewers is passed and truthy, also allows users with
    just reviewer tools view access.

    Don't use on anything that would alter add-on data.

    any_reviewer_required() decorator and AllowAnyKindOfReviewer DRF permission
    use this function behind the scenes to guard views that don't change the
    add-on but still need to be restricted to reviewers only.
    """
    permissions = [
        amo.permissions.ADDONS_REVIEW,
        amo.permissions.ADDONS_REVIEW_UNLISTED,
        amo.permissions.ADDONS_CONTENT_REVIEW,
        amo.permissions.ADDONS_RECOMMENDED_REVIEW,
        amo.permissions.STATIC_THEMES_REVIEW,
    ]
    if allow_viewers:
        permissions.extend(
            [
                amo.permissions.REVIEWER_TOOLS_VIEW,
                amo.permissions.REVIEWER_TOOLS_UNLISTED_VIEW,
            ]
        )
    allow_access = any(action_allowed_user(user, perm) for perm in permissions)
    return allow_access


def author_or_unlisted_viewer_or_reviewer(request, addon):
    return check_unlisted_addons_viewer_or_reviewer(request) or check_addon_ownership(
        request,
        addon,
        allow_addons_edit_permission=False,
        allow_developer=True,
        allow_site_permission=True,
    )
