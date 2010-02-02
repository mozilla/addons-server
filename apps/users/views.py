from django.contrib.auth import logout
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import get_object_or_404

import jingo

from .models import UserProfile
from .signals import logged_out


def profile(request, user_id):
    """user profile display page"""
    user = get_object_or_404(UserProfile, id=user_id)
    return HttpResponse()


def logout_view(request):
    # XXX - we should redirect to /en-US/firefox by default
    redir = request.REQUEST.get('to', '/')
    logout(request)
    # fire logged out signal so we can be decoupled from cake
    response = HttpResponseRedirect(redir)
    logged_out.send(None, request=request, response=response)
    return response
