from rest_framework.exceptions import MethodNotAllowed
from rest_framework.permissions import SAFE_METHODS, BasePermission

from olympia import amo
from olympia.access import acl
from olympia.addons.models import AddonRegionalRestrictions
from olympia.amo import permissions

from .utils import is_gate_active


# Most of these classes come from zamboni, check out
# https://github.com/mozilla/zamboni/blob/master/mkt/api/permissions.py for
# more.


class GroupPermission(BasePermission):
    """
    Allow access depending on the result of action_allowed_for().
    """

    def __init__(self, permission):
        self.permission = permission

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return acl.action_allowed_for(request.user, self.permission)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)

    def __call__(self, *a):
        """
        ignore DRF's nonsensical need to call this object.
        """
        return self


class AnyOf(BasePermission):
    """
    Takes multiple permission objects and succeeds if any single one does.
    """

    def __init__(self, *perms):
        # DRF calls the items in permission_classes, might as well do
        # it here too.
        self.perms = [p() for p in perms]

    def has_permission(self, request, view):
        return any(perm.has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        # This method *must* call `has_permission` for each
        # sub-permission since the default implementation of
        # `has_object_permission` returns True unconditionally, and
        # some permission objects might not override it.
        return any(
            (
                perm.has_permission(request, view)
                and perm.has_object_permission(request, view, obj)
            )
            for perm in self.perms
        )

    def __call__(self):
        return self


class AllOf(BasePermission):
    """
    Takes multiple permission objects and succeeds if all of them do.
    """

    def __init__(self, *perms):
        # DRF calls the items in permission_classes, might as well do
        # it here too.
        self.perms = [p() for p in perms]

    def has_permission(self, request, view):
        return all(perm.has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        # This method *must* call `has_permission` for each
        # sub-permission since the default implementation of
        # `has_object_permission` returns True unconditionally, and
        # some permission objects might not override it.
        return all(
            (
                perm.has_permission(request, view)
                and perm.has_object_permission(request, view, obj)
            )
            for perm in self.perms
        )

    def __call__(self):
        return self


class AllowNone(BasePermission):
    def has_permission(self, request, view):
        return False

    def has_object_permission(self, request, view, obj):
        return False


class AllowAddonAuthor(BasePermission):
    """Allow access if the user is in the object authors."""

    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        return obj.authors.filter(pk=request.user.pk).exists()


class AllowAddonOwner(BasePermission):
    """Allow access if the user is in the object authors, and has an owner role."""

    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        return obj.addonuser_set.filter(
            user_id=request.user.pk, role=amo.AUTHOR_ROLE_OWNER
        ).exists()


class AllowIfNotMozillaDisabled(BasePermission):
    """Allow access unless disabled by mozilla.

    Typically this permission should be used together with AllowAddonAuthor,
    to allow write access to authors unless the add-on was disabled by Mozilla.
    For public-facing API, see AllowReadOnlyIfPublic."""

    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        return obj.status != amo.STATUS_DISABLED


class AllowIfNotSitePermission(BasePermission):
    """Allow access unless the add-on is a site permission.

    Typically this permission should be used together with AllowAddonAuthor,
    to allow write access to authors unless the add-on was a site permission
    add-on.
    For public-facing API, see AllowReadOnlyIfPublic."""

    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        return obj.type != amo.ADDON_SITE_PERMISSION


class AllowOwner(BasePermission):
    """
    Permission class to use when you are dealing with a model instance that has
    a "user" FK pointing to an UserProfile, and you want only the corresponding
    user to be able to access your instance.
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        return (obj == request.user) or (getattr(obj, 'user', None) == request.user)


class AllowNotOwner(AllowOwner):
    """
    Permission class to use when you are dealing with a model instance that has
    a "user" FK pointing to an UserProfile, and you want only the corresponding
    user to be able to access your instance.
    """

    def has_object_permission(self, request, view, obj):
        return not super().has_object_permission(request, view, obj)


class AllowListedViewerOrReviewer(BasePermission):
    """Allow reviewers to access add-ons with listed versions.

    The user logged in must either be making a read-only request and have the
    'ReviewerTools:View' permission, or simply be a reviewer or admin.

    The definition of an add-on reviewer depends on the object:
    - For static themes, it's someone with 'Addons:ThemeReview'
    - For the rest of the add-ons, is someone who has either
      'Addons:Review' or 'Addons:ContentReview' permission.
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        can_access_because_viewer = (
            request.method in SAFE_METHODS
            and acl.action_allowed_for(request.user, permissions.REVIEWER_TOOLS_VIEW)
        )
        can_access_because_listed_reviewer = obj.has_listed_versions(
            include_deleted=True
        ) and acl.is_reviewer(request.user, obj)

        return can_access_because_viewer or can_access_because_listed_reviewer


class AllowUnlistedViewerOrReviewer(AllowListedViewerOrReviewer):
    """Allow unlisted reviewers to access add-ons with unlisted versions, or
    add-ons with no listed versions at all.

    Like reviewers.decorators.unlisted_addons_reviewer_required, but as a
    permission class and not a decorator.

    The user logged in must an unlisted add-on reviewer or admin or have the
    'ReviewerTools:ViewUnlisted' permission.

    An unlisted add-on reviewer is someone who is in the group with the
    following permission: 'Addons:ReviewUnlisted'.
    """

    def has_permission(self, request, view):
        return acl.is_unlisted_addons_viewer_or_reviewer(request.user)

    def has_object_permission(self, request, view, obj):
        can_access_because_unlisted_viewer = (
            request.method in SAFE_METHODS
            and acl.action_allowed_for(
                request.user, permissions.REVIEWER_TOOLS_UNLISTED_VIEW
            )
        )
        can_access_because_unlisted_reviewer = acl.is_unlisted_addons_reviewer(
            request.user
        )
        has_unlisted_or_no_listed = obj.has_unlisted_versions(
            include_deleted=True
        ) or not obj.has_listed_versions(include_deleted=True)

        return has_unlisted_or_no_listed and (
            can_access_because_unlisted_viewer or can_access_because_unlisted_reviewer
        )


class AllowAnyKindOfReviewer(BasePermission):
    """Allow access to any kind of reviewer. Use only for views that don't
    alter add-on data.

    Allows access to users with any of those permissions:
    - ReviewerTools:View (if request is safe)
    - ReviewerTools:ViewUnlisted (if request is safe)
    - Addons:Review
    - Addons:ReviewUnlisted
    - Addons:ContentReview

    Uses acl.is_user_any_kind_of_reviewer() behind the scenes.
    See also any_reviewer_required() decorator.
    """

    def has_permission(self, request, view):
        allow_viewers = request.method in SAFE_METHODS
        return acl.is_user_any_kind_of_reviewer(
            request.user, allow_viewers=allow_viewers
        )

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class AllowIfPublic(BasePermission):
    """
    Allow access when the object's is_public() method returns True.
    """

    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        return obj.is_public() and self.has_permission(request, view)


class AllowReadOnlyIfPublic(AllowIfPublic):
    """
    Allow access when the object's is_public() method returns True and the
    request HTTP method is GET/OPTIONS/HEAD.
    """

    def has_permission(self, request, view):
        return request.method in SAFE_METHODS


class ByHttpMethod(BasePermission):
    """
    Permission class allowing you to define different permissions depending on
    the HTTP method used.

    method_permission is a dict with the lowercase http method names as keys,
    permission classes (not instantiated, like DRF expects them) as values.

    Warning: you probably want to define AllowAny for 'options' if you are
    using a CORS-enabled endpoint.

    If using this permission, any method that does not have a permission set
    will raise MethodNotAllowed.
    """

    def __init__(self, method_permissions):
        # Initialize the permissions by calling them like DRF does.
        self.method_permissions = {
            method: perm() for method, perm in method_permissions.items()
        }

    def has_permission(self, request, view):
        try:
            perm = self.method_permissions[request.method.lower()]
        except KeyError:
            raise MethodNotAllowed(request.method)
        return perm.has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        try:
            perm = self.method_permissions[request.method.lower()]
        except KeyError:
            raise MethodNotAllowed(request.method)
        return perm.has_object_permission(request, view, obj)

    def __call__(self):
        return self


class AllowRelatedObjectPermissions(BasePermission):
    """
    Permission class that tests given permissions against a related object.

    The first argument, `related_property`, is the property that will be used
    to find the related object to test the permissions against.

    The second argument, `related_permissions`, is the list of permissions
    (behaving like DRF default implementation: all need to pass to be allowed).
    """

    def __init__(self, related_property, related_permissions):
        self.perms = [p() for p in related_permissions]
        self.related_property = related_property

    def has_permission(self, request, view):
        return all(perm.has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        related_obj = getattr(obj, self.related_property)
        return all(
            perm.has_object_permission(request, view, related_obj)
            for perm in self.perms
        )

    def __call__(self):
        return self


class PreventActionPermission(BasePermission):
    """
    Allow access except for a given action(s).
    """

    def __init__(self, actions):
        if not isinstance(actions, (list, tuple)):
            actions = [actions]
        self.actions = actions

    def has_permission(self, request, view):
        return getattr(view, 'action', '') not in self.actions

    def has_object_permission(self, request, view, obj):
        return True

    def __call__(self, *a):
        """
        ignore DRF's nonsensical need to call this object.
        """
        return self


class RegionalRestriction(BasePermission):
    """
    Raises a 451 if the add-on is not available because of regional
    restrictions.
    """

    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        region_code = (request and request.META.get('HTTP_X_COUNTRY_CODE', None)) or ''
        qs = AddonRegionalRestrictions.objects.filter(
            addon=obj, excluded_regions__contains=region_code.upper()
        )
        return not (region_code and qs.exists())

    def __call__(self, *a):
        return self


class APIGatePermission(BasePermission):
    def __init__(self, gate):
        self.gate = gate

    def has_permission(self, request, view):
        return is_gate_active(request, self.gate)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)

    def __call__(self, *a):
        return self
