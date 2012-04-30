"""
This middleware will handle marking users into certain groups and loading
their ACLs into the request.
"""
from functools import partial

import commonware.log

import amo
from access import acl
from users.models import RequestUser

log = commonware.log.getLogger('z.access')


class ACLMiddleware(object):

    def process_request(self, request):
        """Attach authentication/permission helpers to request."""
        request.check_ownership = partial(acl.check_ownership, request)

        # figure out our list of groups...
        if request.user.is_authenticated():
            try:
                amo_user = RequestUser.objects.get(pk=request.user.pk)
            except RequestUser.DoesNotExist:
                log.info('No RequestUser found for: %s' % request.user.pk)
                request.amo_user = None
                return

            amo.set_user(amo_user)
            request.user._profile_cache = request.amo_user = amo_user
            request.groups = request.amo_user.groups.all()

            if acl.action_allowed(request, 'Admin', '%'):
                request.user.is_staff = True
        else:
            request.amo_user = None

    def process_response(self, request, response):
        amo.set_user(None)
        return response

    def process_exception(self, request, exception):
        amo.set_user(None)
