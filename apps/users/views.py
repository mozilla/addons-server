from django.contrib.auth import logout
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404

import jingo

import amo
from bandwagon.models import Collection

from .models import UserProfile
from .signals import logged_out


def profile(request, user_id):
    """user profile display page"""
    user = get_object_or_404(UserProfile, id=user_id)

    # get user's own and favorite collections, if they allowed that
    if user.display_collections:
        own_coll = Collection.objects.filter(
            collectionuser__user=user,
            collectionuser__role=amo.COLLECTION_ROLE_ADMIN,
            listed=True).order_by('name')
    else:
        own_coll = []
    if user.display_collections_fav:
        fav_coll = Collection.objects.filter(
            collectionsubscription__user=user,
            listed=True).order_by('name')
    else:
        fav_coll = []

    return jingo.render(request, 'users/profile.html',
                        {'profile': user, 'own_coll': own_coll,
                         'fav_coll': fav_coll})


def logout_view(request):
    # XXX - we should redirect to /en-US/firefox by default
    redir = request.REQUEST.get('to', '/')
    logout(request)
    # fire logged out signal so we can be decoupled from cake
    response = HttpResponseRedirect(redir)
    logged_out.send(None, request=request, response=response)
    return response
