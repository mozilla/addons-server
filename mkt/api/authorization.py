from collections import defaultdict

import commonware.log

from rest_framework.permissions import BasePermission, SAFE_METHODS
from tastypie.authorization import Authorization, ReadOnlyAuthorization
from waffle import flag_is_active, switch_is_active

from access import acl

log = commonware.log.getLogger('z.api')


class OwnerAuthorization(Authorization):

    def is_authorized(self, request, object=None):
        # There is no object being passed, so we'll assume it's ok
        if not object:
            return True
        # There is no request user or no user on the object.
        if not request.amo_user:
            return False

        return self.check_owner(request, object)

    def check_owner(self, request, object):
        if not object.user:
            return False
        # If the user on the object and the amo_user match, we are golden.
        return object.user.pk == request.amo_user.pk


class AppOwnerAuthorization(OwnerAuthorization):

    def check_owner(self, request, object):
        # If the user on the object and the amo_user match, we are golden.
        try:
            if object.authors.filter(user__id=request.amo_user.pk):
                return True

        # Appropriately handles AnonymousUsers when `amo_user` is None.
        except AttributeError:
            return False

        # Reviewers can see non-public apps.
        if request.method == 'GET':
            if acl.action_allowed(request, 'Apps', 'Review'):
                return True


class AnonymousReadOnlyAuthorization(ReadOnlyAuthorization):
    """
    Allows read-only access for anonymous users and optional auth for
    authenticated users.

    If the user is anonymous, only ``GET`` requests are allowed.

    If the user is authenticated, a custom authorization object can be used.
    If no object is set, authenticated users always have access.

    Keyword Arguments

    **authorizer=None**
        If set, this authorization object will be used to check the action for
        authenticated users.
    """

    def __init__(self, *args, **kw):
        self.authorizer = kw.pop('authorizer', None)
        super(AnonymousReadOnlyAuthorization, self).__init__(*args, **kw)

    def is_authorized(self, request, object=None):
        if request.user.is_anonymous():
            sup = super(AnonymousReadOnlyAuthorization, self)
            res = sup.is_authorized(request, object)
            log.info('ReadOnlyAuthorization returned: %s' % res)
            return res
        if self.authorizer:
            res = self.authorizer.is_authorized(request, object)
            log.info('Authorizer %s returned: %s' %
                     (self.authorizer.__class__.__name__, res))
            return res
        return True


class PermissionAuthorization(Authorization):

    def __init__(self, app, action, *args, **kw):
        self.app, self.action = app, action

    def is_authorized(self, request, object=None):
        if acl.action_allowed(request, self.app, self.action):
            return True
        log.info('Permission authorization failed')
        return False

    has_permission = is_authorized


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


class AllowSelf(BasePermission):
    """
    Permission class to use when you are dealing with UserProfile models and
    you want only the corresponding user to be able to access his UserProfile
    instance.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated()

    def has_object_permission(self, request, view, obj):
        try:
            return obj.pk == request.amo_user.pk

        # Appropriately handles AnonymousUsers when `amo_user` is None.
        except AttributeError:
            return False


class AllowNone(BasePermission):

    def has_permission(self, request, view):
        return False

    def has_object_permission(self, request, view, obj):
        return False


class AllowOwner(BasePermission):
    """
    Permission class to use when you are dealing with a model instance that has
    a "user" FK pointing to an UserProfile, and you want only the corresponding
    user to be able to access your instance.

    Do not use with models pointing to an User! There is no guarantee that the
    pk is the same between a User and an UserProfile instance.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated()

    def has_object_permission(self, request, view, obj):
        return obj.user.pk == request.amo_user.pk


class AllowAppOwner(BasePermission):

    def has_permission(self, request, view):
        return not request.user.is_anonymous()

    def has_object_permission(self, request, view, obj):
        try:
            return obj.authors.filter(user__id=request.amo_user.pk).exists()

        # Appropriately handles AnonymousUsers when `amo_user` is None.
        except AttributeError:
            return False


class AllowRelatedAppOwner(BasePermission):

    def has_permission(self, request, view):
        return not request.user.is_anonymous()

    def has_object_permission(self, request, view, obj):
        return AllowAppOwner().has_object_permission(request, view, obj.addon)


class AllowReviewerReadOnly(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS and acl.action_allowed(
            request, 'Apps', 'Review')

    def has_object_permission(self, request, view, object):
        return self.has_permission(request, view)


class AllowReadOnly(BasePermission):
    """
    The request does not modify the resource.
    """
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS

    def has_object_permission(self, request, view, object):
        return request.method in SAFE_METHODS


def flag(name):
    return type('FlagPermission', (WafflePermission,),
                {'type': 'flag', 'name': name})


def switch(name):
    return type('SwitchPermission', (WafflePermission,),
                {'type': 'switch', 'name': name})


class WafflePermission(BasePermission):

    def has_permission(self, request, view):
        if self.type == 'flag':
            return flag_is_active(request, self.name)
        elif self.type == 'switch':
            return switch_is_active(self.name)
        raise NotImplementedError

    def has_object_permission(self, request, view, obj):
        return self.has_permission(request, view)


class GroupPermission(BasePermission):

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
