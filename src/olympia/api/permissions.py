from rest_framework.permissions import BasePermission

from olympia.access import acl


class GroupPermission(BasePermission):
    """
    Comes from zamboni.mkt.api, see #984865 for moving it to it's own project.
    """
    def __init__(self, app, action):
        self.app = app
        self.action = action

    def has_permission(self, request, view):
        return acl.action_allowed(request, self.app, self.action)

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)

    def __call__(self, *a):
        """
        ignore DRF's nonsensical need to call this object.
        """
        return self
