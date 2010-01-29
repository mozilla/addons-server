from django import http
from django.shortcuts import get_object_or_404
from django.contrib import auth
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from l10n import ugettext as _

import jingo

import amo
from bandwagon.models import Collection

from .models import UserProfile
from .signals import logged_out
from .users import models as users


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
    auth.logout(request)
    # fire logged out signal so we can be decoupled from cake
    response = http.HttpResponseRedirect(redir)
    logged_out.send(None, request=request, response=response)
    return response


@login_required
def user_edit(request):
    amouser = request.user.get_profile()
    if request.method == 'POST':
        form = users.UserEditForm(request.POST)
        if form.is_valid():
            # XXX TODO process the data
            messages.success(request, _('Profile Updated'))
        else:
            messages.error(request, _('There were errors in the changes you '
                                    'made. Please correct them and resubmit.'))
    else:
        form = users.UserEditForm(instance=amouser)

    return jingo.render(request, 'users/user_edit.html',
                        {'form': form, 'amouser': amouser})
