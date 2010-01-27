from django.contrib.auth import logout
from django.http import HttpResponseRedirect

from .signals import logged_out


def logout_view(request):
    # XXX - we should redirect to /en-US/firefox by default
    redir = request.REQUEST.get('to', '/')
    logout(request)
    # fire logged out signal so we can be decoupled from cake
    response = HttpResponseRedirect(redir)
    logged_out.send(None, request=request, response=response)
    return response
