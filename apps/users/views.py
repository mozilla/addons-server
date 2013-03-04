from datetime import datetime, timedelta
from functools import partial
from urlparse import urlparse

from django import http
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.contrib import auth
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.template import Context, loader
from django.utils.datastructures import SortedDict
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils.encoding import smart_str
from django.utils.http import base36_to_int

from django_browserid import get_audience, verify
from waffle.decorators import waffle_flag, waffle_switch

import commonware.log
from django_statsd.clients import statsd
import jingo
from radagast.wizard import Wizard
from tower import ugettext as _, ugettext_lazy as _lazy
from session_csrf import anonymous_csrf, anonymous_csrf_exempt
from mobility.decorators import mobile_template
import waffle

from access.middleware import ACLMiddleware
import amo
from amo import messages
from amo.decorators import (json_view, login_required, permission_required,
                            post_required, write)
from amo.forms import AbuseForm
from amo.urlresolvers import get_url_prefix, reverse
from amo.helpers import loc
from amo.utils import escape_all, log_cef, send_mail
from abuse.models import send_abuse_report
from addons.models import Addon
from addons.views import BaseFilter
from addons.decorators import addon_view_factory
from access import acl
from bandwagon.models import Collection
from market.models import PreApprovalUser
import paypal
from stats.models import Contribution
from translations.query import order_by_translation
from users.models import UserNotification
import users.notifications as notifications

from lib.metrics import record_action

from .models import UserProfile
from .signals import logged_out
from . import forms
from .utils import EmailResetCode, UnsubscribeCode, autocreate_username
import tasks

log = commonware.log.getLogger('z.users')
paypal_log = commonware.log.getLogger('z.paypal')

addon_view = addon_view_factory(qs=Addon.objects.valid)


@login_required(redirect=False)
@json_view
def ajax(request):
    """Query for a user matching a given email."""

    if 'q' not in request.GET:
        raise http.Http404()

    data = {'status': 0, 'message': ''}

    email = request.GET.get('q', '').strip()
    dev_only = request.GET.get('dev', '1')
    try:
        dev_only = int(dev_only)
    except ValueError:
        dev_only = 1
    dev_only = dev_only and settings.MARKETPLACE

    if not email:
        data.update(message=_('An email address is required.'))
        return data

    user = UserProfile.objects.filter(email=email)
    if dev_only:
        user = user.exclude(read_dev_agreement=None)

    msg = _('A user with that email address does not exist.')
    msg_dev = _('A user with that email address does not exist, or the user '
                'has not yet accepted the developer agreement.')

    if user:
        data.update(status=1, id=user[0].id, name=user[0].name)
    else:
        data['message'] = msg_dev if dev_only else msg

    return escape_all(data)


def confirm(request, user_id, token):
    user = get_object_or_404(UserProfile, id=user_id)

    if not user.confirmationcode:
        return redirect('users.login')

    if user.confirmationcode != token:
        log.info(u"Account confirmation failed for user (%s)", user)
        messages.error(request, _('Invalid confirmation code!'))
        return redirect('users.login')

    user.confirmationcode = ''
    user.save()
    messages.success(request, _('Successfully verified!'))
    log.info(u"Account confirmed for user (%s)", user)
    return redirect('users.login')


def confirm_resend(request, user_id):
    user = get_object_or_404(UserProfile, id=user_id)

    if not user.confirmationcode:
        return redirect('users.login')

    # Potential for flood here if someone requests a confirmationcode and then
    # re-requests confirmations.  We may need to track requests in the future.
    log.info(u"Account confirm re-requested for user (%s)", user)

    user.email_confirmation_code()

    msg = _(u'An email has been sent to your address {0} to confirm '
             'your account. Before you can log in, you have to activate '
             'your account by clicking on the link provided in this '
             'email.').format(user.email)
    messages.info(request, _('Confirmation Email Sent'), msg)

    return redirect('users.login')


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
    webapp = settings.APP_PREVIEW
    # Don't use request.amo_user since it has too much caching.
    amouser = UserProfile.objects.get(pk=request.user.id)
    if request.method == 'POST':
        # ModelForm alters the instance you pass in.  We need to keep a copy
        # around in case we need to use it below (to email the user)
        original_email = amouser.email
        form = forms.UserEditForm(request.POST, request.FILES, request=request,
                                  instance=amouser, webapp=webapp)
        if form.is_valid():
            messages.success(request, _('Profile Updated'))
            if amouser.email != original_email:
                # Temporarily block email changes.
                if settings.APP_PREVIEW:
                    messages.error(request, 'Error',
                                   'You cannot change your email on the '
                                   'developer preview site.')
                    return jingo.render(request, 'users/edit.html',
                                        {'form': form, 'amouser': amouser})

                l = {'user': amouser,
                     'mail1': original_email,
                     'mail2': amouser.email}
                log.info(u"User (%(user)s) has requested email change from "
                          "(%(mail1)s) to (%(mail2)s)" % l)
                messages.info(request, _('Email Confirmation Sent'),
                    _(u'An email has been sent to {0} to confirm your new '
                       'email address. For the change to take effect, you '
                       'need to click on the link provided in this email. '
                       'Until then, you can keep logging in with your '
                       'current email address.').format(amouser.email))

                token, hash_ = EmailResetCode.create(amouser.id, amouser.email)
                url = '%s%s' % (settings.SITE_URL,
                                reverse('users.emailchange',
                                        args=[amouser.id, token, hash_]))
                t = loader.get_template('users/email/emailchange.ltxt')
                c = {'domain': settings.DOMAIN, 'url': url}
                send_mail(_('Please confirm your email address '
                            'change at %s' % settings.DOMAIN),
                    t.render(Context(c)), None, [amouser.email],
                    use_blacklist=False, real_email=True)

                # Reset the original email back.  We aren't changing their
                # address until they confirm the new one
                amouser.email = original_email
            form.save()
            return redirect('users.edit')
        else:

            messages.error(request, _('Errors Found'),
                                    _('There were errors in the changes '
                                      'you made. Please correct them and '
                                      'resubmit.'))
    else:
        form = forms.UserEditForm(instance=amouser, webapp=webapp)
    return jingo.render(request, 'users/edit.html',
                        {'form': form, 'amouser': amouser, 'webapp': webapp})


@write
@login_required
@permission_required('Users', 'Edit')
def admin_edit(request, user_id):
    amouser = get_object_or_404(UserProfile, pk=user_id)

    if request.method == 'POST':
        form = forms.AdminUserEditForm(request.POST, request.FILES,
                                       request=request, instance=amouser)
        if form.is_valid():
            form.save()
            messages.success(request, _('Profile Updated'))
            return http.HttpResponseRedirect(reverse('zadmin.index'))
    else:
        form = forms.AdminUserEditForm(instance=amouser)
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
    url = gets.get('to', settings.LOGIN_REDIRECT_URL)

    parsed = urlparse(url)
    if ((parsed.scheme and parsed.scheme not in ['http', 'https'])
        or parsed.netloc):
        log.info(u'Unsafe redirect to %s' % url)
        url = settings.LOGIN_REDIRECT_URL

    domain = gets.get('domain', None)
    if domain in settings.VALID_LOGIN_REDIRECTS.keys():
        url = settings.VALID_LOGIN_REDIRECTS[domain] + url

    gets['to'] = url
    request.GET = gets
    return request


def browserid_authenticate(request, assertion, is_native=False):
    """
    Verify a BrowserID login attempt. If the BrowserID assertion is
    good, but no account exists, create one.

    """
    url = settings.BROWSERID_VERIFICATION_URL
    extra_params = None
    if is_native:
        # When persona is running native on B2G then we need to
        # verify assertions with the right service.
        # We also need to force the appropriate issuer
        # for potentially unverified emails.
        url = settings.NATIVE_BROWSERID_VERIFICATION_URL
        extra_params = {'forceIssuer': settings.UNVERIFIED_ISSUER or False,
                        'allowUnverified': 'true'}

    audience = get_audience(request)
    log.debug('Verifying Persona at %s, audience: %s, '
              'extra_params: %s' % (url, audience, extra_params))
    result = verify(assertion, audience,
                    url=url, extra_params=extra_params)
    if not result:
        return None, _('Persona authentication failure.')

    if 'unverified-email' in result:
        email = result['unverified-email']
        verified = False
    else:
        email = result['email']
        verified = True

    try:
        profile = UserProfile.objects.filter(email=email)[0]
    except IndexError:
        profile = None

    if profile:
        if profile.is_verified and not verified:
            # An attempt to log in to a verified address with an unverified
            # assertion is a very bad thing. However, the same email address
            # can legitimately be used on the site on desktop and be verified
            # whilst be used on b2g and be unverified. We are forcing the
            # issuer, so this shouldn't be an issue.
            #
            # Blame kumar. Or cvan. Or deal with it.
            log.debug('Verified user %s attempted to log in with an '
                      'unverified assertion!' % profile)
        else:
            profile.is_verified = verified
            profile.save()

        backend = 'django_browserid.auth.BrowserIDBackend'
        if getattr(profile.user, 'backend', None) != backend:
            profile.user.backend = backend
            profile.user.save()

        return profile, None

    username = autocreate_username(email.partition('@')[0])
    source = (amo.LOGIN_SOURCE_MMO_BROWSERID if settings.MARKETPLACE else
              amo.LOGIN_SOURCE_AMO_BROWSERID)
    profile = UserProfile.objects.create(username=username, email=email,
                                         source=source, display_name=username,
                                         is_verified=verified)
    profile.create_django_user(
        backend='django_browserid.auth.BrowserIDBackend')
    log_cef('New Account', 5, request, username=username,
            signature='AUTHNOTICE',
            msg='User created a new account (from Persona)')
    record_action('new-user', request)
    return profile, None


@csrf_exempt
@post_required
@transaction.commit_on_success
#@ratelimit(block=True, rate=settings.LOGIN_RATELIMIT_ALL_USERS)
def browserid_login(request):
    msg = ''
    if waffle.switch_is_active('browserid-login'):
        if request.user.is_authenticated():
            # If username is different, maybe sign in as new user?
            return http.HttpResponse(status=200)
        try:
            is_native = bool(int(request.POST.get('is_native', 0)))
        except ValueError:
            is_native = False
        with statsd.timer('auth.browserid.verify'):
            profile, msg = browserid_authenticate(
                request, request.POST['assertion'],
                is_native=is_native)
        if profile is not None:
            auth.login(request, profile.user)
            profile.log_login_attempt(True)
            return http.HttpResponse(status=200)
    return http.HttpResponse(msg, status=401)


@anonymous_csrf
@mobile_template('users/{mobile/}login_modal.html')
#@ratelimit(block=True, rate=settings.LOGIN_RATELIMIT_ALL_USERS)
def login_modal(request, template=None):
    return _login(request, template=template)


@anonymous_csrf
@mobile_template('users/{mobile/}login.html')
#@ratelimit(block=True, rate=settings.LOGIN_RATELIMIT_ALL_USERS)
def login(request, template=None):
    if settings.MARKETPLACE:
        return redirect('users.login')
    return _login(request, template=template)


def _login(request, template=None, data=None, dont_redirect=False):
    data = data or {}
    data['webapp'] = settings.APP_PREVIEW
    # In case we need it later.  See below.
    get_copy = request.GET.copy()

    if 'to' in request.GET:
        request = _clean_next_url(request)

    if request.user.is_authenticated():
        return http.HttpResponseRedirect(
            request.GET.get('to', settings.LOGIN_REDIRECT_URL))

    limited = getattr(request, 'limited', 'recaptcha_shown' in request.POST)
    user = None
    login_status = None
    if 'username' in request.POST:
        try:
            # We are doing all this before we try and validate the form.
            user = UserProfile.objects.get(email=request.POST['username'])
            limited = ((user.failed_login_attempts >=
                        settings.LOGIN_RATELIMIT_USER) or limited)
            login_status = False
        except UserProfile.DoesNotExist:
            log_cef('Authentication Failure', 5, request,
                    username=request.POST['username'],
                    signature='AUTHFAIL',
                    msg='The username was invalid')
            pass

    partial_form = partial(forms.AuthenticationForm, use_recaptcha=limited)
    r = auth.views.login(request, template_name=template,
                         redirect_field_name='to',
                         authentication_form=partial_form,
                         extra_context=data)

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
            data.update({'form': partial_form()})
            user.log_login_attempt(False)
            log_cef('Authentication Failure', 5, request,
                    username=request.user,
                    signature='AUTHFAIL',
                    msg='Account is deactivated')
            return jingo.render(request, template, data)

        if user.confirmationcode:
            logout(request)
            log.info(u'Attempt to log in with unconfirmed account (%s)' % user)
            msg1 = _(u'A link to activate your user account was sent by email '
                      'to your address {0}. You have to click it before you '
                      'can log in.').format(user.email)
            url = "%s%s" % (settings.SITE_URL,
                            reverse('users.confirm.resend', args=[user.id]))
            msg2 = _('If you did not receive the confirmation email, make '
                      'sure your email service did not mark it as "junk '
                      'mail" or "spam". If you need to, you can have us '
                      '<a href="%s">resend the confirmation message</a> '
                      'to your email address mentioned above.') % url
            messages.error(request, _('Activation Email Sent'), msg1)
            messages.info(request, _('Having Trouble?'), msg2,
                          title_safe=True, message_safe=True)
            data.update({'form': partial_form()})
            user.log_login_attempt(False)
            return jingo.render(request, template, data)

        rememberme = request.POST.get('rememberme', None)
        if rememberme:
            request.session.set_expiry(settings.SESSION_COOKIE_AGE)
            log.debug((u'User (%s) logged in successfully with '
                                        '"remember me" set') % user)

        login_status = True

        if dont_redirect:
            # We're recalling the middleware to re-initialize amo_user
            ACLMiddleware().process_request(request)
            r = jingo.render(request, template, data)

    if login_status is not None:
        user.log_login_attempt(login_status)
        log_cef('Authentication Failure', 5, request,
                username=request.POST['username'],
                signature='AUTHFAIL',
                msg='The password was incorrect')

    return r


def logout(request):
    # Not using get_profile() becuase user could be anonymous
    user = request.user
    if not user.is_anonymous():
        log.debug(u"User (%s) logged out" % user)

    auth.logout(request)

    if 'to' in request.GET:
        request = _clean_next_url(request)

    next = request.GET.get('to')
    if not next:
        next = settings.LOGOUT_REDIRECT_URL
        prefixer = get_url_prefix()
        if prefixer:
            next = prefixer.fix(next)
    response = http.HttpResponseRedirect(next)
    # Fire logged out signal.
    logged_out.send(None, request=request, response=response)
    return response


def profile(request, user_id):
    # Temporary until we decide we want user profile pages.
    if settings.MARKETPLACE:
        raise http.Http404

    webapp = settings.APP_PREVIEW
    user = get_object_or_404(UserProfile, id=user_id)

    # Get user's own and favorite collections, if they allowed that.
    own_coll = fav_coll = []
    if not webapp:
        if user.display_collections:
            own_coll = (Collection.objects.listed().filter(author=user)
                        .order_by('-created'))[:10]
        if user.display_collections_fav:
            fav_coll = (Collection.objects.listed()
                        .filter(following__user=user)
                        .order_by('-following__created'))[:10]

    edit_any_user = acl.action_allowed(request, 'Users', 'Edit')
    own_profile = (request.user.is_authenticated() and
                   request.amo_user.id == user.id)

    personas = []
    if user.is_developer:
        if webapp:
            items = user.apps_listed
        else:
            items = user.addons_listed.exclude(type=amo.ADDON_PERSONA)
            personas = user.addons_listed.filter(type=amo.ADDON_PERSONA)
        addons = amo.utils.paginate(request,
                                    items.order_by('-weekly_downloads'))
    else:
        addons = []

    def get_addons(reviews):
        if not reviews:
            return
        qs = Addon.objects.filter(id__in=set(r.addon_id for r in reviews))
        addons = dict((addon.id, addon) for addon in qs)
        for review in reviews:
            review.addon = addons.get(review.addon_id)
    # (Don't show marketplace reviews for AMO (since that would break))
    reviews = list(user.reviews.exclude(addon__type=amo.ADDON_WEBAPP)
                   .transform(get_addons))

    data = {'profile': user, 'own_coll': own_coll, 'reviews': reviews,
            'fav_coll': fav_coll, 'edit_any_user': edit_any_user,
            'addons': addons, 'own_profile': own_profile,
            'webapp': webapp, 'personas': personas}
    if not own_profile:
        data['abuse_form'] = AbuseForm(request=request)

    return jingo.render(request, 'users/profile.html', data)


@anonymous_csrf
def register(request):

    if settings.APP_PREVIEW and waffle.switch_is_active('browserid-login'):
        messages.error(request,
                       loc('Registrations must be through browserid.'))
        form = None
        raise http.Http404()

    elif request.user.is_authenticated():
        messages.info(request, _('You are already logged in to an account.'))
        form = None

    elif request.method == 'POST':

        form = forms.UserRegisterForm(request.POST)
        mkt_user = UserProfile.objects.filter(email=form.data['email'],
                                              password='')
        if form.is_valid():
            try:
                u = form.save(commit=False)
                u.set_password(form.cleaned_data['password'])
                u.generate_confirmationcode()
                u.save()
                u.create_django_user()
                log.info(u'Registered new account for user (%s)', u)
                log_cef('New Account', 5, request, username=u.username,
                        signature='AUTHNOTICE',
                        msg='User created a new account')

                u.email_confirmation_code()

                msg = _('Congratulations! Your user account was '
                        'successfully created.')
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
                # case to the end user so we just log it...
                log.error('Failed to register new user (%s): %s' % (u, e))

            return http.HttpResponseRedirect(reverse('users.login'))

        elif mkt_user.exists():
            # Handle BrowserID
            if (mkt_user.count() == 1 and
                mkt_user[0].source in amo.LOGIN_SOURCE_BROWSERIDS):
                messages.info(request, _('You already have an account.'))
                form = None
            else:
                f = PasswordResetForm()
                f.users_cache = [mkt_user[0]]
                f.save(use_https=request.is_secure(),
                       email_template_name='users/email/pwreset.ltxt',
                        request=request)
                return jingo.render(request, 'users/newpw_sent.html', {})
        else:
            messages.error(request, _('There are errors in this form'),
                            _('Please correct them and resubmit.'))
    else:
        form = forms.UserRegisterForm()

    reg_action = reverse('users.register')
    return jingo.render(request, 'users/register.html',
                        {'form': form, 'register_action': reg_action})


@anonymous_csrf_exempt
def report_abuse(request, user_id):
    user = get_object_or_404(UserProfile, pk=user_id)
    form = AbuseForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        send_abuse_report(request, user, form.cleaned_data['text'])
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
                log_cef('Password Changed', 5, request,
                        username=user.username,
                        signature='PASSWORDCHANGED',
                        msg='User changed password')
                return redirect(reverse('django.contrib.auth.'
                                        'views.password_reset_complete'))
        else:
            form = forms.SetPasswordForm(user)
    else:
        validlink = False
        form = None

    return jingo.render(request, 'users/pwreset_confirm.html',
                        {'form': form, 'validlink': validlink})


@never_cache
def unsubscribe(request, hash=None, token=None, perm_setting=None):
    """
    Pulled from django contrib so that we can add user into the form
    so then we can show relevant messages about the user.
    """
    assert hash is not None and token is not None
    user = None

    try:
        email = UnsubscribeCode.parse(token, hash)
        user = UserProfile.objects.get(email=email)
    except (ValueError, UserProfile.DoesNotExist):
        pass

    perm_settings = []
    if user is not None:
        unsubscribed = True
        if not perm_setting:
            # TODO: make this work. nothing currently links to it, though.
            perm_settings = [l for l in notifications.NOTIFICATIONS
                             if not l.mandatory]
        else:
            perm_setting = notifications.NOTIFICATIONS_BY_SHORT[perm_setting]
            UserNotification.update_or_create(update={'enabled': False},
                    user=user, notification_id=perm_setting.id)
            perm_settings = [perm_setting]
    else:
        unsubscribed = False
        email = ''

    return jingo.render(request, 'users/unsubscribe.html',
            {'unsubscribed': unsubscribed, 'email': email,
             'perm_settings': perm_settings})


class PurchasesFilter(BaseFilter):
    opts = (('purchased', loc('Purchase Date')),
            ('price', _lazy(u'Price')),
            ('name', _lazy(u'Name')))

    def filter(self, field):
        qs = self.base_queryset
        if field == 'purchased':
            return (qs.filter(Q(addonpurchase__user=self.request.amo_user) |
                              Q(addonpurchase__isnull=True))
                    .order_by('-addonpurchase__created', 'id'))
        elif field == 'price':
            return qs.order_by('addonpremium__price__price', 'id')
        elif field == 'name':
            return order_by_translation(qs, 'name')


# TODO(cvan): I'll remove this view when it doesn't break every single thing.
@login_required
@mobile_template('users/{mobile/}purchases.html')
@waffle_switch('marketplace')
def purchases(request, addon_id=None, template=None):
    """A list of purchases that a user has made through the marketplace."""
    webapp = settings.APP_PREVIEW
    cs = (Contribution.objects
          .filter(user=request.amo_user,
                  type__in=[amo.CONTRIB_PURCHASE, amo.CONTRIB_REFUND,
                            amo.CONTRIB_CHARGEBACK])
          .order_by('created'))
    if addon_id:
        cs = cs.filter(addon=addon_id)

    ids = list(cs.values_list('addon_id', flat=True))
    # If you are asking for a receipt for just one item, only show that.
    # Otherwise, we'll show all addons that have a contribution or are free.
    if not addon_id:
        ids += list(request.amo_user.installed_set
                    .exclude(addon__in=ids)
                    .values_list('addon_id', flat=True))

    contributions = {}
    for c in cs:
        contributions.setdefault(c.addon_id, []).append(c)

    ids = list(set(ids))
    addons = Addon.objects.filter(id__in=ids)
    if webapp:
        addons = addons.filter(type=amo.ADDON_WEBAPP)

    filter = PurchasesFilter(request, addons, key='sort', default='purchased')

    if addon_id and not filter.qs:
        # User has requested a receipt for an addon they don't have.
        raise http.Http404

    addons = amo.utils.paginate(request, filter.qs, count=len(ids))
    return jingo.render(request, template,
                        {'addons': addons,
                         'webapp': webapp,
                         'filter': filter,
                         'contributions': contributions,
                         'single': bool(addon_id)})


# Start of the Support wizard all of these are accessed through the
# SupportWizard below.
def plain(request, contribution, wizard):
    # Simple view that just shows a template matching the step.
    tpl = wizard.tpl('%s.html' % wizard.step)
    addon = contribution.addon
    return wizard.render(request, tpl, {'addon': addon,
                                        'webapp': addon.is_webapp(),
                                        'contribution': contribution})


def support_author(request, contribution, wizard):
    addon = contribution.addon
    form = forms.ContactForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            template = jingo.render_to_string(
                request, wizard.tpl('emails/support-request.txt'),
                context={'contribution': contribution, 'addon': addon,
                         'form': form, 'user': request.amo_user})
            log.info('Support request to dev. by user: %s for addon: %s' %
                     (request.amo_user.pk, addon.pk))
            # L10n: %s is the addon name.
            send_mail(_(u'New Support Request for %s' % addon.name),
                      template, request.amo_user.email,
                      [smart_str(addon.support_email)])
            return redirect(reverse('users.support',
                                    args=[contribution.pk, 'author-sent']))

    return wizard.render(request, wizard.tpl('author.html'),
                         {'addon': addon, 'webapp': addon.is_webapp(),
                          'form': form})


def support_mozilla(request, contribution, wizard):
    addon = contribution.addon
    form = forms.ContactForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            template = jingo.render_to_string(
                request, wizard.tpl('emails/support-request.txt'),
                context={'addon': addon, 'form': form,
                         'contribution': contribution,
                         'user': request.amo_user})
            log.info('Support request to mozilla by user: %s for addon: %s' %
                     (request.amo_user.pk, addon.pk))
            # L10n: %s is the addon name.
            send_mail(_(u'New Support Request for %s' % addon.name),
                      template, request.amo_user.email,
                      [settings.MARKETPLACE_EMAIL])
            return redirect(reverse('users.support',
                                    args=[contribution.pk, 'mozilla-sent']))

    return wizard.render(request, wizard.tpl('mozilla.html'),
                         {'addon': addon, 'form': form})


@waffle_switch('allow-refund')
def refund_request(request, contribution, wizard):
    addon = contribution.addon
    webapp = addon.is_webapp()
    form = forms.RemoveForm(request.POST or None)
    if request.method == 'POST' and (webapp or form.is_valid()):
        return redirect('users.support', contribution.pk, 'reason')

    return wizard.render(request, wizard.tpl('request.html'),
                         {'addon': addon, 'webapp': webapp,
                          'form': form, 'contribution': contribution})


@waffle_switch('allow-refund')
def refund_reason(request, contribution, wizard):
    addon = contribution.addon
    if not 'request' in wizard.get_progress():
        return redirect('users.support', contribution.pk, 'request')
    if contribution.transaction_id is None:
        messages.error(request,
                       _('A refund cannot be applied for yet. Please try again'
                         ' later. If this error persists contact '
                         'apps-marketplace@mozilla.org.'))
        paypal_log.info('Refund requested for contribution with no '
                        'transaction_id: %r' % (contribution.pk,))
        return redirect('users.purchases')

    if contribution.is_instant_refund():
        paypal.refund(contribution.paykey)
        # TODO: Consider requiring a refund reason for instant refunds.
        refund = contribution.enqueue_refund(amo.REFUND_APPROVED_INSTANT)
        paypal_log.info('Refund %r issued for contribution %r' %
                        (refund.pk, contribution.pk))
        # Note: we have to wait for PayPal to issue an IPN before it's
        # completely refunded.
        messages.success(request, _('Refund is being processed.'))
        return redirect('users.purchases')

    form = forms.ContactForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        reason = form.cleaned_data['text']
        template = jingo.render_to_string(request,
            wizard.tpl('emails/refund-request.txt'),
            context={'addon': addon,
                     'form': form,
                     'user': request.amo_user,
                     'contribution': contribution,
                     'refund_url': contribution.get_absolute_refund_url(),
                     'refund_reason': reason})
        log.info('Refund request sent by user: %s for addon: %s' %
                 (request.amo_user.pk, addon.pk))
        # L10n: %s is the addon name.
        send_mail(_(u'New Refund Request for %s' % addon.name),
                  template, settings.NOBODY_EMAIL,
                  [smart_str(addon.support_email)])
        # Add this refund request to the queue.
        contribution.enqueue_refund(amo.REFUND_PENDING, reason)
        return redirect(reverse('users.support',
                                args=[contribution.pk, 'refund-sent']))

    return wizard.render(request, wizard.tpl('refund.html'), {'form': form})


class SupportWizard(Wizard):
    title = _lazy('Support')
    steps = SortedDict((('start', plain),
                ('site', plain),
                ('resources', plain),
                ('mozilla', support_mozilla),
                ('mozilla-sent', plain),
                ('author', support_author),
                ('author-sent', plain),
                ('request', refund_request),
                ('reason', refund_reason),
                ('refund-sent', plain)))

    def tpl(self, x):
        return 'users/support/%s' % x

    @property
    def wrapper(self):
        return self.tpl('{mobile/}wrapper.html')

    @method_decorator(login_required)
    def dispatch(self, request, contribution_id, step='', *args, **kw):
        contribution = get_object_or_404(Contribution, pk=contribution_id)
        if contribution.user.pk != request.amo_user.pk:
            raise http.Http404
        args = [contribution] + list(args)
        return super(SupportWizard, self).dispatch(request, step, *args, **kw)

    def render(self, request, template, context):
        fmt = {'mobile/': 'mobile/' if request.MOBILE else ''}
        wrapper = self.wrapper.format(**fmt)
        context.update(wizard=self)
        if request.is_ajax():
            return jingo.render(request, template, context)
        context['content'] = template
        return jingo.render(request, wrapper, context)


@login_required
@waffle_flag('allow-pre-auth')
def payments(request, status=None):
    # Note this is not post required, because PayPal does not reply with a
    # POST but a GET, that's a sad face.
    if status:
        pre, created = (PreApprovalUser.objects
                        .safer_get_or_create(user=request.amo_user))

        if status == 'complete':
            # The user has completed the setup at PayPal and bounced back.
            if 'setup-preapproval' in request.session:
                messages.success(request, loc('Pre-approval set up.'))
                paypal_log.info(u'Preapproval key created for user: %s'
                                % request.amo_user)
                data = request.session.get('setup-preapproval', {})
                pre.update(paypal_key=data.get('key'),
                           paypal_expiry=data.get('expiry'))
                del request.session['setup-preapproval']

        elif status == 'cancel':
            # The user has chosen to cancel out of PayPal. Nothing really
            # to do here, PayPal just bounces to this page.
            messages.success(request, loc('Pre-approval changes cancelled.'))

        elif status == 'remove':
            # The user has an pre approval key set and chooses to remove it
            if pre.paypal_key:
                pre.update(paypal_key='')
                messages.success(request, loc('Pre-approval removed.'))
                paypal_log.info(u'Preapproval key removed for user: %s'
                                % request.amo_user)

        context = {'preapproval': pre}
    else:
        context = {'preapproval': request.amo_user.get_preapproval()}

    return jingo.render(request, 'users/payments.html', context)


@post_required
@login_required
@waffle_flag('allow-pre-auth')
def preapproval(request):
    today = datetime.today()
    data = {'startDate': today,
            'endDate': today + timedelta(days=365 * 2),
            'pattern': 'users.payments',
            }
    try:
        result = paypal.get_preapproval_key(data)
    except paypal.PaypalError, e:
        paypal_log.error(u'Preapproval key: %s' % e, exc_info=True)
        raise

    paypal_log.info(u'Got preapproval key for user: %s' % request.amo_user.pk)
    request.session['setup-preapproval'] = {'key': result['preapprovalKey'],
                                            'expiry': data['endDate']}
    to = paypal.get_preapproval_url(result['preapprovalKey'])
    return http.HttpResponseRedirect(to)
