"""
Middleware to help interface with the legacy Cake PHP client.
"""
from django.conf import settings
from django.contrib import auth

import commonware.log

from users.signals import logged_out
from .models import Session
from .utils import handle_logout

logged_out.connect(handle_logout)

log = commonware.log.getLogger('z.cake')


class CakeCookieMiddleware(object):
    """
    This middleware will extract a cookie named AMOv3, take the session id,
    look it up in our cake_sessions table, and use that to authenticate a
    logged in user.
    """

    def process_request(self, request):
        """
        Look up the AMOv3 session id in the table and login the user if it's
        valid.
        """
        if request.user.is_authenticated() or settings.READ_ONLY:
            return

        id = request.COOKIES.get('AMOv3')

        if id:
            try:
                session = Session.objects.get(pk=id)
                user = auth.authenticate(session=session)
                if user is not None:
                    auth.login(request, user)
            except Session.DoesNotExist:
                return


class CookieCleaningMiddleware(object):
    "Removes old remora-specific cookies that are long dead."

    def process_response(self, request, response):
        # TODO(davedash): Remove this method when we no longer get any of these
        # loggged.
        if request.COOKIES.get('locale-only'):
            log.debug("Removed a locale-only cookie.")
            response.delete_cookie('locale-only')
        return response
