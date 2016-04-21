"""
This middleware will handle marking users into certain groups and loading
their ACLs into the request.
"""
from functools import partial

import commonware.log

from olympia import amo
from olympia.access import acl

log = commonware.log.getLogger('z.access')


class ACLMiddleware(object):

    def process_request(self, request):
        """Attach authentication/permission helpers to request."""
        request.check_ownership = partial(acl.check_ownership, request)

        # Persist the user in the thread to make it accessible in log()
        # statements etc.
        if request.user.is_authenticated():
            amo.set_user(request.user)

    def process_response(self, request, response):
        amo.set_user(None)
        return response

    def process_exception(self, request, exception):
        amo.set_user(None)
