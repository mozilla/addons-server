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
        if object.authors.filter(user__id=request.amo_user.pk):
            return True
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


class AllowNone(BasePermission):

    def has_permission(self, request, view):
        return False

    def has_object_permission(self, request, view, obj):
        return False


class AllowAppOwner(BasePermission):

    def has_permission(self, request, view):
        return not request.user.is_anonymous()

    def has_object_permission(self, request, view, object):
        return AppOwnerAuthorization().check_owner(request, object)


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
