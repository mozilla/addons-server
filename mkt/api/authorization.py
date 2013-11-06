import commonware.log

from rest_framework.permissions import BasePermission
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


class AllowSelf(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated()

    def has_object_permission(self, request, view, object):
        try:
            return object.pk == request.amo_user.pk

        # Appropriately handles AnonymousUsers when `amo_user` is None.
        except AttributeError:
            return False


class AllowNone(BasePermission):

    def has_permission(self, request, view):
        return False

    def has_object_permission(self, request, view, obj):
        return False


class AllowOwner(BasePermission):

    def has_permission(self, request, view):
        return request.user.is_authenticated()

    def has_object_permission(self, request, view, obj):
        return obj.user.pk == request.amo_user.pk


class AllowAppOwner(BasePermission):

    def has_permission(self, request, view):
        return not request.user.is_anonymous()

    def has_object_permission(self, request, view, object):
        try:
            return object.authors.filter(user__id=request.amo_user.pk).exists()

        # Appropriately handles AnonymousUsers when `amo_user` is None.
        except AttributeError:
            return False


class AllowAppOwnerOrPermission(BasePermission):
    """
    Allows app owners or users with the specified permission.
    """
    def __init__(self, app, action):
        self.app = app
        self.action = action

    def has_permission(self, request, view):
        return not request.user.is_anonymous()

    def has_object_permission(self, request, view, object):
        try:
            return (
                acl.action_allowed(request, self.app, self.action) or
                object.authors.filter(user__id=request.amo_user.pk).exists())

        # Appropriately handles AnonymousUsers when `amo_user` is None.
        except AttributeError:
            return False

    def __call__(self, *a):
        """
        Ignore DRF's nonsensical need to call this object.
        """
        return self


class AllowReviewerReadOnly(BasePermission):

    def is_authorized(self, request, object=None):
        if request.method == 'GET' and acl.action_allowed(request,
                                                          'Apps', 'Review'):
            return True


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


class GroupPermission(BasePermission):

    def __init__(self, app, action):
        self.app = app
        self.action = action

    def has_permission(self, request, view):
        return acl.action_allowed(request, self.app, self.action)

    def __call__(self, *a):
        """
        ignore DRF's nonsensical need to call this object.
        """
        return self
