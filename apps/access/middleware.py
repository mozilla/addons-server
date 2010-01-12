"""
This middleware will handle marking users into certain groups and loading
their ACLs into the request
"""


class ACLMiddleware(object):

    def process_request(self, request):
        """
        mark all users as is_admin, this is open source!
        """

        # figure out our list of groups...
        if request.user.is_authenticated():
            request.amo_user = request.user.get_profile()
            request.groups = request.amo_user.group_set.all()

            if '*:*' in [v.rules for v in request.groups]:
                request.user.is_superuser = True
                request.user.is_staff = True
