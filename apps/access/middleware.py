"""
This middleware will handle marking users into certain groups and loading
their ACLs into the request.
"""


class ACLMiddleware(object):

    def process_request(self, request):
        """
        Keep groups as part of the request.
        """

        # figure out our list of groups...
        if request.user.is_authenticated():
            request.amo_user = request.user.get_profile()
            request.groups = request.amo_user.group_set.all()
