from collections import defaultdict

from rest_framework.permissions import BasePermission, SAFE_METHODS

from olympia.access import acl


# Most of these classes come from zamboni, check out
# https://github.com/mozilla/zamboni/blob/master/mkt/api/permissions.py for
# more.

class GroupPermission(BasePermission):
    """
    Allow access depending on the result of action_allowed_user().
    """
    def __init__(self, app, action):
        self.app = app
        self.action = action

    def has_permission(self, request, view):
        if not request.user.is_authenticated():
            return False
        return acl.action_allowed_user(request.user, self.app, self.action)

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
        return any((perm.has_permission(request, view) and
                    perm.has_object_permission(request, view, obj))
                   for perm in self.perms)

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
        return request.user.is_authenticated()

    def has_object_permission(self, request, view, obj):
        return obj.authors.filter(pk=request.user.pk).exists()


class AllowOwner(BasePermission):
    """
    Permission class to use when you are dealing with a model instance that has
    a "user" FK pointing to an UserProfile, and you want only the corresponding
    user to be able to access your instance.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated()

    def has_object_permission(self, request, view, obj):
        return ((obj == request.user) or
                (getattr(obj, 'user', None) == request.user))


class AllowReviewer(BasePermission):
    """Allow addons reviewer access.

    Like editors.decorators.addons_reviewer_required, but as a permission class
    and not a decorator.

    The user logged in must either be making a read-only request and have the
    'ReviewerTools:View' permission, or simply be a reviewer or admin.

    An add-on reviewer is someone who is in the group with the following
    permission: 'Addons:Review'.
    """
    def has_permission(self, request, view):
        return ((request.method in SAFE_METHODS and
                 acl.action_allowed(request, 'ReviewerTools', 'View')) or
                acl.check_addons_reviewer(request))

    def has_object_permission(self, request, view, obj):
        return obj.is_listed and self.has_permission(request, view)


class AllowReviewerUnlisted(AllowReviewer):
    """Allow unlisted addons reviewer access.

    Like editors.decorators.unlisted_addons_reviewer_required, but as a
    permission class and not a decorator.

    The user logged in must an unlisted add-on reviewer or admin.

    An unlisted add-on reviewer is someone who is in the group with the
    following permission: 'Addons:Review'.
    """
    def has_permission(self, request, view):
        return acl.check_unlisted_addons_reviewer(request)

    def has_object_permission(self, request, view, obj):
        return not obj.is_listed and self.has_permission(request, view)


class AllowIfReviewedAndListed(BasePermission):
    """
    Allow access when the object's is_public() method and is_listed property
    both return True.
    """
    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        return (obj.is_reviewed() and not obj.disabled_by_user and
                obj.is_listed and self.has_permission(request, view))


class AllowReadOnlyIfReviewedAndListed(AllowIfReviewedAndListed):
    """
    Allow access when the object's is_public() method and is_listed property
    both return True and the request HTTP method is GET/OPTIONS/HEAD.
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
    """
    def __init__(self, method_permissions, default=None):
        if default is None:
            default = AllowNone()
        self.method_permissions = defaultdict(lambda: default)
        for method, perm in method_permissions.items():
            # Initialize the permissions by calling them like DRF does.
            self.method_permissions[method] = perm()

    def has_permission(self, request, view):
        perm = self.method_permissions[request.method.lower()]
        return perm.has_permission(request, view)

    def has_object_permission(self, request, view, obj):
        perm = self.method_permissions[request.method.lower()]
        return perm.has_object_permission(request, view, obj)

    def __call__(self):
        return self


class AllowRelatedObjectPermissions(BasePermission):
    def __init__(self, related_property, related_permissions):
        self.perms = related_permissions
        self.related_property = related_property

    def has_permission(self, request, view):
        return all(perm.has_permission(request, view) for perm in self.perms)

    def has_object_permission(self, request, view, obj):
        related_obj = getattr(obj, self.related_property)
        return all(perm.has_object_permission(request, view, related_obj)
                   for perm in self.perms)

    def __call__(self):
        return self
