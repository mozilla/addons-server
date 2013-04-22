import commonware.log
from tastypie.authorization import Authorization, ReadOnlyAuthorization

from access import acl

log = commonware.log.getLogger('z.api')


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
