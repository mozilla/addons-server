"""
This middleware will handle marking users into certain groups and loading
their ACLs into the request.
"""

from access import acl


class ACLMiddleware(object):

    def process_request(self, request):
        """
        Keep groups as part of the request.
        """

        # figure out our list of groups...
        if request.user.is_authenticated():
            request.amo_user = request.user.get_profile()
            request.groups = request.amo_user.groups.all()

            if acl.action_allowed(request, 'Admin', '%'):
                request.user.is_staff = True
