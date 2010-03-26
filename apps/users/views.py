import logging
from django import http
from django.core.mail import send_mail
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.contrib import auth
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.template import Context, loader

from l10n import ugettext as _

import jingo

import amo
from bandwagon.models import Collection
from manage import settings

from .models import UserProfile
from .signals import logged_out
from .users import forms
from users.utils import EmailResetCode

log = logging.getLogger('z.users')


@login_required
def delete(request):
    amouser = request.user.get_profile()
    if request.method == 'POST':
        form = forms.UserDeleteForm(request.POST, request=request)
        if form.is_valid():
            messages.success(request, _('Profile Deleted'))
            amouser.anonymize()
            logout(request)
            form = None
    else:
        form = forms.UserDeleteForm()

    return jingo.render(request, 'delete.html',
                        {'form': form, 'amouser': amouser})


@login_required
def edit(request):
    amouser = request.user.get_profile()
    if request.method == 'POST':
        # ModelForm alters the instance you pass in.  We need to keep a copy
        # around in case we need to use it below (to email the user)
        original_email = amouser.email
        form = forms.UserEditForm(request.POST, request=request,
                                  instance=amouser)
        if form.is_valid():
            messages.success(request, _('Profile Updated'))
            if amouser.email != original_email:
                l = {'user': amouser,
                     'mail1': original_email,
                     'mail2': amouser.email}
                log.info(("User (%(user)s) has requested email change from"
                            "(%(mail1)s) to (%(mail2)s)") % l)
                messages.info(request, _(('An email has been sent to {0} to '
                    'confirm your new email address. For the change to take '
                    'effect, you need to click on the link provided in this '
                    'email. Until then, you can keep logging in with your '
                    'current email address.').format(amouser.email)))

                domain = settings.DOMAIN
                token, hash = EmailResetCode.create(amouser.id, amouser.email)
                url = "%s%s" % (settings.SITE_URL,
                                reverse('users.emailchange', args=[amouser.id,
                                                                token, hash]))
                t = loader.get_template('email/emailchange.ltxt')
                c = {'domain': domain, 'url': url, }
                send_mail(_(("Please confirm your email address "
                             "change at %s") % domain),
                    t.render(Context(c)), None, [amouser.email])

                # Reset the original email back.  We aren't changing their
                # address until they confirm the new one
                amouser.email = original_email
            form.save()
        else:
            messages.error(request, _('There were errors in the changes '
                                      'you made. Please correct them and '
                                      'resubmit.'))
    else:
        form = forms.UserEditForm(instance=amouser)

    return jingo.render(request, 'edit.html',
                        {'form': form, 'amouser': amouser})


def emailchange(request, user_id, token, hash):
    user = get_object_or_404(UserProfile, id=user_id)

    try:
        _uid, newemail = EmailResetCode.parse(token, hash)
    except ValueError:
        return http.HttpResponse(status=400)

    if _uid != user.id:
        # I'm calling this a warning because invalid hashes up to this point
        # could be any number of things, but this is a targeted attack from
        # one user account to another
        log.warning(("[Tampering] Valid email reset code for UID (%s) "
                     "attempted to change email address for user (%s)")
                                                        % (_uid, user))
        return http.HttpResponse(status=400)

    user.email = newemail
    user.save()

    l = {'user': user, 'newemail': newemail}
    log.info("User (%(user)s) confirmed new email address (%(newemail)s)" % l)
    messages.success(request, _(('Your email address was changed '
                                 'successfully.  From now on, please use {0} '
                                 'to log in.')).format(newemail))

    return http.HttpResponseRedirect(reverse('users.edit'))


def login(request):
    logout(request)
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
        log.debug("User (%s) logged out" % user)

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
