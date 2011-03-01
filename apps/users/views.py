from django import http
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect
from django.contrib import auth
from django.template import Context, loader

import commonware.log
import jingo
from tower import ugettext as _


import amo
from amo import messages
from amo.decorators import login_required, json_view, write
from amo.forms import AbuseForm
from amo.urlresolvers import reverse
from amo.utils import send_mail, send_abuse_report
from addons.models import Addon
from access import acl
from bandwagon.models import Collection

from .models import UserProfile
from .signals import logged_out
from . import forms
from .utils import EmailResetCode
import tasks

log = commonware.log.getLogger('z.users')


@login_required(redirect=False)
@json_view
def ajax(request):
    """Query for a user matching a given email."""
    email = request.GET.get('q', '').strip()
    u = get_object_or_404(UserProfile, email=email)
    return dict(id=u.id, name=u.name)


def confirm(request, user_id, token):
    user = get_object_or_404(UserProfile, id=user_id)

    if not user.confirmationcode:
        return http.HttpResponseRedirect(reverse('users.login'))

    if user.confirmationcode != token:
        log.info(u"Account confirmation failed for user (%s)", user)
        messages.error(request, _('Invalid confirmation code!'))

        amo.utils.clear_messages(request)
        return http.HttpResponseRedirect(reverse('users.login') + '?m=5')
        # TODO POSTREMORA Replace the above with this line when
        # remora goes away
        #return http.HttpResponseRedirect(reverse('users.login'))

    user.confirmationcode = ''
    user.save()
    messages.success(request, _('Successfully verified!'))
    log.info(u"Account confirmed for user (%s)", user)

    amo.utils.clear_messages(request)
    return http.HttpResponseRedirect(reverse('users.login') + '?m=4')
    # TODO POSTREMORA Replace the above with this line when remora goes away
    #return http.HttpResponseRedirect(reverse('users.login'))


def confirm_resend(request, user_id):
    user = get_object_or_404(UserProfile, id=user_id)

    if not user.confirmationcode:
        return http.HttpResponseRedirect(reverse('users.login'))

    # Potential for flood here if someone requests a confirmationcode and then
    # re-requests confirmations.  We may need to track requests in the future.
    log.info(u"Account confirm re-requested for user (%s)", user)

    user.email_confirmation_code()

    msg = _('An email has been sent to your address {0} to confirm '
            'your account. Before you can log in, you have to activate '
            'your account by clicking on the link provided in this '
            'email.').format(user.email)
    messages.info(request, msg)

    return http.HttpResponseRedirect(reverse('users.login'))


@login_required
def delete(request):
    amouser = request.amo_user
    if request.method == 'POST':
        form = forms.UserDeleteForm(request.POST, request=request)
        if form.is_valid():
            messages.success(request, _('Profile Deleted'))
            amouser.anonymize()
            logout(request)
            form = None
            return http.HttpResponseRedirect(reverse('users.login'))
    else:
        form = forms.UserDeleteForm()

    return jingo.render(request, 'users/delete.html',
                        {'form': form, 'amouser': amouser})


@login_required
def delete_photo(request):
    u = request.amo_user

    if request.method == 'POST':
        u.picture_type = ''
        u.save()
        log.debug(u"User (%s) deleted photo" % u)
        tasks.delete_photo.delay(u.picture_path)
        messages.success(request, _('Photo Deleted'))
        return http.HttpResponseRedirect(reverse('users.edit') +
                                         '#user-profile')

    return jingo.render(request, 'users/delete_photo.html', dict(user=u))


@write
@login_required
def edit(request):
    # Don't use request.amo_user since it has too much caching.
    amouser = UserProfile.objects.get(pk=request.user.id)
    if request.method == 'POST':
        # ModelForm alters the instance you pass in.  We need to keep a copy
        # around in case we need to use it below (to email the user)
        original_email = amouser.email
        form = forms.UserEditForm(request.POST, request.FILES, request=request,
                                  instance=amouser)
        if form.is_valid():
            messages.success(request, _('Profile Updated'))
            if amouser.email != original_email:
                l = {'user': amouser,
                     'mail1': original_email,
                     'mail2': amouser.email}
                log.info(u"User (%(user)s) has requested email change from"
                          "(%(mail1)s) to (%(mail2)s)" % l)
                messages.info(request, _(('An email has been sent to {0} to '
                    'confirm your new email address. For the change to take '
                    'effect, you need to click on the link provided in this '
                    'email. Until then, you can keep logging in with your '
                    'current email address.')).format(amouser.email))

                domain = settings.DOMAIN
                token, hash = EmailResetCode.create(amouser.id, amouser.email)
                url = "%s%s" % (settings.SITE_URL,
                                reverse('users.emailchange', args=[amouser.id,
                                                                token, hash]))
                t = loader.get_template('users/email/emailchange.ltxt')
                c = {'domain': domain, 'url': url, }
                send_mail(_(("Please confirm your email address "
                             "change at %s") % domain),
                    t.render(Context(c)), None, [amouser.email],
                    use_blacklist=False)

                # Reset the original email back.  We aren't changing their
                # address until they confirm the new one
                amouser.email = original_email
            form.save()
            return http.HttpResponseRedirect(reverse('users.edit'))
        else:

            messages.error(request, _('There were errors in the changes '
                                      'you made. Please correct them and '
                                      'resubmit.'))
    else:
        form = forms.UserEditForm(instance=amouser)

    return jingo.render(request, 'users/edit.html',
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
        log.warning((u"[Tampering] Valid email reset code for UID (%s) "
                     "attempted to change email address for user (%s)")
                                                        % (_uid, user))
        return http.HttpResponse(status=400)

    user.email = newemail
    user.save()

    l = {'user': user, 'newemail': newemail}
    log.info(u"User (%(user)s) confirmed new email address (%(newemail)s)" % l)
    messages.success(request, _(('Your email address was changed '
                                 'successfully.  From now on, please use {0} '
                                 'to log in.')).format(newemail))

    return http.HttpResponseRedirect(reverse('users.edit'))


def _clean_next_url(request):
    gets = request.GET.copy()
    url = gets['to']

    # We want to not redirect outside of AMO via login/logout.
    if url and '://' in url:
        url = '/'

    # TODO(davedash): This is a remora-ism, let's remove this after remora and
    # since all zamboni 'to' parameters will begin with '/'.
    if url and not url.startswith('/'):
        url = '/' + url

    gets['to'] = url
    request.GET = gets
    return request


def login(request):
    logout(request)

    if 'to' in request.GET:
        request = _clean_next_url(request)

    r = auth.views.login(request, template_name='users/login.html',
                         redirect_field_name='to',
                         authentication_form=forms.AuthenticationForm)

    if isinstance(r, http.HttpResponseRedirect):
        # Succsesful log in according to django.  Now we do our checks.  I do
        # the checks here instead of the form's clean() because I want to use
        # the messages framework and it's not available in the request there
        user = request.user.get_profile()

        if user.deleted:
            logout(request)
            log.warning(u'Attempt to log in with deleted account (%s)' % user)
            messages.error(request, _('Wrong email address or password!'))
            return jingo.render(request, 'users/login.html',
                                {'form': forms.AuthenticationForm()})

        if user.confirmationcode:
            logout(request)
            log.info(u'Attempt to log in with unconfirmed account (%s)' % user)
            msg1 = _(('A link to activate your user account was sent by email '
                      'to your address {0}. You have to click it before you '
                      'can log in.').format(user.email))
            url = "%s%s" % (settings.SITE_URL,
                            reverse('users.confirm.resend', args=[user.id]))
            msg2 = _(('If you did not receive the confirmation email, make '
                      'sure your email service did not mark it as "junk '
                      'mail" or "spam". If you need to, you can have us '
                      '<a href="%s">resend the confirmation message</a> '
                      'to your email address mentioned above.') % url)
            messages.error(request, msg1)
            messages.info(request, msg2, title_safe=True)
            return jingo.render(request, 'users/login.html',
                                {'form': forms.AuthenticationForm()})

        rememberme = request.POST.get('rememberme', None)
        if rememberme:
            request.session.set_expiry(settings.SESSION_COOKIE_AGE)
            log.debug((u'User (%s) logged in successfully with '
                                        '"remember me" set') % user)
        else:
            user.log_login_attempt(request, True)
    elif 'username' in request.POST:
        # Hitting POST directly because cleaned_data doesn't exist
        user = UserProfile.objects.filter(email=request.POST['username'])
        if user:
            user.get().log_login_attempt(request, False)

    return r


def logout(request):
    # Not using get_profile() becuase user could be anonymous
    user = request.user
    if not user.is_anonymous():
        log.debug(u"User (%s) logged out" % user)

    auth.logout(request)

    if 'to' in request.GET:
        request = _clean_next_url(request)

    next = request.GET.get('to') or settings.LOGOUT_REDIRECT_URL
    response = http.HttpResponseRedirect(next)
    # Fire logged out signal so we can be decoupled from cake.
    logged_out.send(None, request=request, response=response)
    return response


def profile(request, user_id):
    """user profile display page"""
    user = get_object_or_404(UserProfile, id=user_id)

    # get user's own and favorite collections, if they allowed that
    if user.display_collections:
        own_coll = (Collection.objects.listed().filter(author=user)
                    .order_by('-created'))[:10]
    else:
        own_coll = []
    if user.display_collections_fav:
        fav_coll = (Collection.objects.listed()
                    .filter(following__user=user)
                    .order_by('-following__created'))[:10]
    else:
        fav_coll = []

    edit_any_user = acl.action_allowed(request, 'Admin', 'EditAnyUser')
    own_profile = request.user.is_authenticated() and (
        request.amo_user.id == user.id)

    if user.is_developer:
        addons = amo.utils.paginate(
                    request,
                    user.addons_listed.order_by('-weekly_downloads'))
    else:
        addons = []

    def get_addons(reviews):
        if not reviews:
            return
        qs = Addon.objects.filter(id__in=set(r.addon_id for r in reviews))
        addons = dict((addon.id, addon) for addon in qs)
        for review in reviews:
            review.addon = addons.get(review.addon_id)
    reviews = user.reviews.transform(get_addons)

    data = {'profile': user, 'own_coll': own_coll, 'reviews': reviews,
            'fav_coll': fav_coll, 'edit_any_user': edit_any_user,
            'addons': addons, 'own_profile': own_profile}

    if settings.REPORT_ABUSE:
        data['abuse_form'] = AbuseForm(request=request)

    return jingo.render(request, 'users/profile.html', data)


def register(request):
    if request.user.is_authenticated():
        messages.info(request, _("You are already logged in to an account."))
        form = None
    elif request.method == 'POST':

        form = forms.UserRegisterForm(request.POST)

        if form.is_valid():
            u = form.save(commit=False)
            u.set_password(form.cleaned_data['password'])
            u.generate_confirmationcode()
            u.save()
            u.create_django_user()
            log.info(u"Registered new account for user (%s)", u)

            u.email_confirmation_code()

            messages.success(request, _('Congratulations! Your user account '
                                        'was successfully created.'))
            msg = _(('An email has been sent to your address {0} to confirm '
                     'your account. Before you can log in, you have to '
                     'activate your account by clicking on the link provided '
                     ' in this email.').format(u.email))
            messages.info(request, msg)

            amo.utils.clear_messages(request)
            return http.HttpResponseRedirect(reverse('users.login') + '?m=3')
            # TODO POSTREMORA Replace the above with this line
            # when remora goes away
            #return http.HttpResponseRedirect(reverse('users.login'))

        else:
            messages.error(request, _(('There are errors in this form. Please '
                                       'correct them and resubmit.')))
    else:
        form = forms.UserRegisterForm()
    return jingo.render(request, 'users/register.html', {'form': form, })


def report_abuse(request, user_id):
    if not settings.REPORT_ABUSE:
        raise http.Http404()

    user = get_object_or_404(UserProfile, pk=user_id)
    form = AbuseForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        url = reverse('users.profile', args=[user.pk])
        send_abuse_report(request, user, url, form.cleaned_data['text'])
        messages.success(request, _('User reported.'))
    else:
        return jingo.render(request, 'users/report_abuse_full.html',
                            {'profile': user, 'abuse_form': form, })
    return redirect(reverse('users.profile', args=[user.pk]))
