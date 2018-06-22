"""
This middleware will handle marking users into certain groups and loading
their ACLs into the request.
"""
from functools import partial

import olympia.core.logger

from olympia import core
from olympia.access import acl


class UserAndAddrMiddleware(object):

    def process_request(self, request):
        """Attach authentication/permission helpers to request, and persist
        user and remote addr in current thread."""
        request.check_ownership = partial(acl.check_ownership, request)

        # Persist the user and remote addr in the thread to make it accessible
        # in log() statements etc.
        if request.user.is_authenticated():
            core.set_user(request.user)
        core.set_remote_addr(request.META.get('REMOTE_ADDR'))

    def process_response(self, request, response):
        core.set_user(None)
        core.set_remote_addr(None)
        return response

    def process_exception(self, request, exception):
        core.set_user(None)
        core.set_remote_addr(None)
