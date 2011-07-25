from functools import partial

from django import http
from django.conf import settings
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect
from django.contrib import auth
from django.template import Context, loader
from django.views.decorators.cache import never_cache
from django.utils.http import base36_to_int
from django.contrib.auth.tokens import default_token_generator

import commonware.log
import jingo
from ratelimit.decorators import ratelimit
from tower import ugettext as _
from session_csrf import anonymous_csrf, anonymous_csrf_exempt


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

    msg = _(u'An email has been sent to your address {0} to confirm '
             'your account. Before you can log in, you have to activate '
             'your account by clicking on the link provided in this '
             'email.').format(user.email)
    messages.info(request, _('Confirmation Email Sent'), msg)

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
def edit_impala(request):
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
                messages.info(request, _('Email Confirmation Sent'),
                    _(u'An email has been sent to {0} to confirm your new '
                       'email address. For the change to take effect, you '
                       'need to click on the link provided in this email. '
                       'Until then, you can keep logging in with your '
                       'current email address.').format(amouser.email))

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
            return http.HttpResponseRedirect(reverse('users.edit_impala'))
        else:

            messages.error(request, _('Errors Found'),
                                    _('There were errors in the changes '
                                      'you made. Please correct them and '
                                      'resubmit.'))
    else:
        form = forms.UserEditForm(instance=amouser)

    return jingo.render(request, 'users/edit_impala.html',
                        {'form': form, 'amouser': amouser})


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
                messages.info(request, _('Email Confirmation Sent'),
                    _(u'An email has been sent to {0} to confirm your new '
                       'email address. For the change to take effect, you '
                       'need to click on the link provided in this email. '
                       'Until then, you can keep logging in with your '
                       'current email address.').format(amouser.email))

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

            messages.error(request, _('Errors Found'),
                                    _('There were errors in the changes '
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
    messages.success(request, _('Your email address was changed successfully'),
            _(u'From now on, please use {0} to log in.').format(newemail))

    return http.HttpResponseRedirect(reverse('users.edit'))


def _clean_next_url(request):
    gets = request.GET.copy()
    url = gets['to']

    if not url:
        url = settings.LOGIN_REDIRECT_URL

    # We want to not redirect outside of AMO via login/logout (also see
    # "domain" below)
    if '://' in url:
        url = '/'

    # TODO(davedash): This is a remora-ism, let's remove this after remora and
    # since all zamboni 'to' parameters will begin with '/'.
    if url and not url.startswith('/'):
        url = '/' + url

    gets['to'] = url

    domain = gets.get('domain', None)
    if domain in settings.VALID_LOGIN_REDIRECTS.keys():
        gets['to'] = "%s%s" % (settings.VALID_LOGIN_REDIRECTS[domain], url)

    request.GET = gets
    return request


@anonymous_csrf
@ratelimit(block=True, rate=settings.LOGIN_RATELIMIT_ALL_USERS)
def login(request):
    # In case we need it later.  See below.
    get_copy = request.GET.copy()

    logout(request)

    if 'to' in request.GET:
        request = _clean_next_url(request)

    limited = getattr(request, 'limited', 'recaptcha_shown' in request.POST)
    partial_form = partial(forms.AuthenticationForm, use_recaptcha=limited)
    r = auth.views.login(request, template_name='users/login.html',
                         redirect_field_name='to',
                         authentication_form=partial_form)

    if isinstance(r, http.HttpResponseRedirect):
        # Django's auth.views.login has security checks to prevent someone from
        # redirecting to another domain.  Since we want to allow this in
        # certain cases, we have to make a new response object here to replace
        # the above.
        if 'domain' in request.GET:
            request.GET = get_copy
            request = _clean_next_url(request)
            r = http.HttpResponseRedirect(request.GET['to'])

        # Succsesful log in according to django.  Now we do our checks.  I do
        # the checks here instead of the form's clean() because I want to use
        # the messages framework and it's not available in the request there.
        user = request.user.get_profile()

        if user.deleted:
            logout(request)
            log.warning(u'Attempt to log in with deleted account (%s)' % user)
            messages.error(request, _('Wrong email address or password!'))
            return jingo.render(request, 'users/login.html',
                                {'form': partial_form()})

        if user.confirmationcode:
            logout(request)
            log.info(u'Attempt to log in with unconfirmed account (%s)' % user)
            msg1 = _(u'A link to activate your user account was sent by email '
                      'to your address {0}. You have to click it before you '
                      'can log in.').format(user.email)
            url = "%s%s" % (settings.SITE_URL,
                            reverse('users.confirm.resend', args=[user.id]))
            msg2 = _(('If you did not receive the confirmation email, make '
                      'sure your email service did not mark it as "junk '
                      'mail" or "spam". If you need to, you can have us '
                      '<a href="%s">resend the confirmation message</a> '
                      'to your email address mentioned above.') % url)
            messages.error(request, _('Activation Email Sent'),  msg1)
            messages.info(request, _('Having Trouble?'), msg2,
                          title_safe=True)
            return jingo.render(request, 'users/login.html',
                                {'form': partial_form()})

        if (user.failed_login_attempts > settings.LOGIN_RATELIMIT_USER
            and not limited):
            # This reshows the form with the recaptcha. Until they are logged
            # in we don't know if the user needs to have recaptcha shown.
            # The UX for this isn't good, we should fix this.
            logout(request)
            log.info(u'Attempt to log in with too many failures (%s)' % user)
            form = forms.AuthenticationForm(request.POST, use_recaptcha=True)
            return jingo.render(request, 'users/login.html', {'form': form})

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
            'addons': addons, 'own_profile': own_profile,
            'abuse_form': AbuseForm(request=request)}

    return jingo.render(request, 'users/profile.html', data)


@anonymous_csrf
def register(request):
    if request.user.is_authenticated():
        messages.info(request, _("You are already logged in to an account."))
        form = None
    elif request.method == 'POST':

        form = forms.UserRegisterForm(request.POST)

        if form.is_valid():
            try:
                u = form.save(commit=False)
                u.set_password(form.cleaned_data['password'])
                u.generate_confirmationcode()
                u.save()
                u.create_django_user()
                log.info(u"Registered new account for user (%s)", u)

                u.email_confirmation_code()

                msg = _('Congratulations! Your user account was successfully '
                        'created.')
                messages.success(request, msg)

                msg = _(u'An email has been sent to your address {0} to '
                         'confirm your account. Before you can log in, you '
                         'have to activate your account by clicking on the '
                         'link provided in this email.').format(u.email)
                messages.info(request, _('Confirmation Email Sent'), msg)
            except IntegrityError, e:
                # I was unable to reproduce this, but I suspect it happens
                # when they POST twice quickly and the slaves don't have the
                # new info yet (total guess).  Anyway, I'm assuming the
                # first one worked properly, so this is still a success
                # case to tne end user so we just log it...
                log.error("Failed to register new user (%s): %s" % (u, e))

            amo.utils.clear_messages(request)
            return http.HttpResponseRedirect(reverse('users.login') + '?m=3')
            # TODO POSTREMORA Replace the above two lines
            # when remora goes away with this:
            #return http.HttpResponseRedirect(reverse('users.login'))

        else:
            messages.error(request, _('There are errors in this form'),
                            _('Please correct them and resubmit.'))
    else:
        form = forms.UserRegisterForm()
    return jingo.render(request, 'users/register.html', {'form': form, })


@anonymous_csrf_exempt
def report_abuse(request, user_id):
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


@never_cache
def password_reset_confirm(request, uidb36=None, token=None):
    """
    Pulled from django contrib so that we can add user into the form
    so then we can show relevant messages about the user.
    """
    assert uidb36 is not None and token is not None
    user = None
    try:
        uid_int = base36_to_int(uidb36)
        user = UserProfile.objects.get(id=uid_int)
    except (ValueError, UserProfile.DoesNotExist):
        pass

    if user is not None and default_token_generator.check_token(user, token):
        validlink = True
        if request.method == 'POST':
            form = forms.SetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()
                return redirect(reverse('django.contrib.auth.'
                                        'views.password_reset_complete'))
        else:
            form = forms.SetPasswordForm(user)
    else:
        validlink = False
        form = None

    return jingo.render(request, 'users/pwreset_confirm.html',
                        {'form': form, 'validlink': validlink})
