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


class AllowAddonAuthor(BasePermission):
    """Allow access if the user is in the object authors."""
    def has_permission(self, request, view):
        return request.user.is_authenticated()

    def has_object_permission(self, request, view, obj):
        return obj.authors.filter(pk=request.user.pk).exists()


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


class AllowReadOnlyIfPublicAndListed(BasePermission):
    """
    Allow access when the object's is_public() method and is_listed property
    both return True and the request HTTP method is GET/OPTIONS/HEAD.
    """
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS

    def has_object_permission(self, request, view, obj):
        return (obj.is_public() and obj.is_listed and
                self.has_permission(request, view))
