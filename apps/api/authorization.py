from collections import defaultdict

import commonware.log

from rest_framework.permissions import BasePermission


log = commonware.log.getLogger('z.api')


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
        # This method must call `has_permission` for each
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


class AllowAppOwner(BasePermission):

    def has_permission(self, request, view):
        return not request.user.is_anonymous()

    def has_object_permission(self, request, view, obj):
        try:
            return obj.authors.filter(pk=request.amo_user.pk).exists()

        # Appropriately handles AnonymousUsers when `amo_user` is None.
        except AttributeError:
            return False


class ByHttpMethod(BasePermission):
    """
    Permission class allowing you to define different Permissions depending on
    the HTTP method used.

    method_permission is a dict with the lowercase http method names as keys,
    permission classes (not instantiated, like DRF expects them) as values.

    Careful, you probably want to define AllowAny for 'options' if you are
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
