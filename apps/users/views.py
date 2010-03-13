import logging
from django import http
from django.shortcuts import get_object_or_404
from django.contrib import auth
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseRedirect

from l10n import ugettext as _

import jingo

import amo
from bandwagon.models import Collection
from manage import settings

from .models import UserProfile
from .signals import logged_out
from .users import forms

log = logging.getLogger('z.users')


@login_required
def edit(request):
    amouser = request.user.get_profile()
    if request.method == 'POST':
        form = forms.UserEditForm(request.POST, request=request,
                                  instance=amouser)
        if form.is_valid():
            messages.success(request, _('Profile Updated'))
            form.save()
        else:
            messages.error(request, _('There were errors in the changes '
                                      'you made. Please correct them and '
                                      'resubmit.'))
    else:
        form = forms.UserEditForm(instance=amouser)

    return jingo.render(request, 'edit.html',
                        {'form': form, 'amouser': amouser})


def login(request):
    r = auth.views.login(request, template_name='login.html',
                         authentication_form=forms.AuthenticationForm)
    form = forms.AuthenticationForm(data=request.POST)
    form.is_valid()  # clean the data

    if isinstance(r, HttpResponseRedirect):
        # Succsesful log in
        user = request.user.get_profile()
        if form.cleaned_data['rememberme']:
            request.session.set_expiry(settings.SESSION_COOKIE_AGE)
            log.debug(('User (%s) logged in successfully with'
                                        '"remember me" set') % user)
        else:
            log.debug("User (%s) logged in successfully" % user)

    else:
        # Hitting POST directly because cleaned_data doesn't exist
        if 'username' in request.POST:
            log.debug(u"User (%s) failed to log in" %
                                            request.POST['username'])

    return r


def logout(request):
    # Not using get_profile() becuase user could be anonymous
    user = request.user
    if not user.is_anonymous():
        log.info("User (%s) logged out" % user)

    auth.logout(request)
    response = http.HttpResponseRedirect(settings.LOGOUT_REDIRECT_URL)
    # fire logged out signal so we can be decoupled from cake
    logged_out.send(None, request=request, response=response)
    return response


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
