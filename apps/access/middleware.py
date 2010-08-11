"""
This middleware will handle marking users into certain groups and loading
their ACLs into the request.
"""

from access import acl
from users.models import UserProfile


class ACLMiddleware(object):

    def process_request(self, request):
        """
        Keep groups as part of the request.
        """

        # figure out our list of groups...
        if request.user.is_authenticated():
            amo_user = (UserProfile.objects.request_user()
                        .get(pk=request.user.pk))
            request.user._profile_cache = request.amo_user = amo_user
            request.groups = request.amo_user.groups.all()

            if acl.action_allowed(request, 'Admin', '%'):
                request.user.is_staff = True
