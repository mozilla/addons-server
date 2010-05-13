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

        id = request.COOKIES.get('AMOv3')

        if id:
            try:
                session = Session.objects.get(pk=id)
                user = auth.authenticate(session=session)
                if user is not None:
                    SESSION_KEY = '_auth_user_id'
                    BACKEND_SESSION_KEY = '_auth_user_backend'
                    if SESSION_KEY in request.session:
                        if request.session[SESSION_KEY] != user.id:
                            # To avoid reusing another user's session, create a new, empty
                            # session if the existing session corresponds to a different
                            # authenticated user.
                            request.session.flush()
                    else:
                        request.session.cycle_key()
                    request.session[SESSION_KEY] = user.id
                    request.session[BACKEND_SESSION_KEY] = user.backend
                    request.user = user
            except Session.DoesNotExist:
                return
