"""
Middleware to help interface with the legacy Cake PHP client.
"""
from django.contrib import auth

from users.signals import logged_out

from .models import Session
from .utils import handle_logout

logged_out.connect(handle_logout)


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
        if request.user.is_authenticated():
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
