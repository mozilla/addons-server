import commonware.log
from rest_framework.permissions import BasePermission

from access import acl

log = commonware.log.getLogger('mkt.collections')


class PublisherAuthorization(BasePermission):

    def has_permission(self, request, view):
        if (request.method == 'GET' or
            acl.action_allowed(request, 'Apps', 'Publisher')):
            return True
        log.info('Publisher authorization failed')
        return False
