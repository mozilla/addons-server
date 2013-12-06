import functools
from functools import partial

from django import http
from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import (get_list_or_404, get_object_or_404,
                              redirect)
from django.contrib import auth
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.template import Context, loader
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.utils.http import base36_to_int, is_safe_url

import commonware.log
import jingo
import waffle
from django_browserid import get_audience, verify
from django_statsd.clients import statsd
from mobility.decorators import mobile_template
from session_csrf import anonymous_csrf, anonymous_csrf_exempt
from tower import ugettext as _

import amo
import users.notifications as notifications
from abuse.models import send_abuse_report
from access.middleware import ACLMiddleware
from addons.decorators import addon_view_factory
from addons.models import Addon, Category
from amo import messages
from amo.decorators import (json_view, login_required, permission_required,
                            post_required, write)
from amo.forms import AbuseForm
from amo.helpers import loc
from amo.urlresolvers import get_url_prefix, reverse
from amo.utils import escape_all, log_cef, send_mail
from access import acl
from bandwagon.models import Collection
from browse.views import PersonasFilter
from translations.query import order_by_translation
from users.models import UserNotification

from lib.metrics import record_action

from .models import UserProfile
from .signals import logged_out
from . import forms
from .utils import autocreate_username, EmailResetCode, UnsubscribeCode
import tasks

log = commonware.log.getLogger('z.users')

addon_view = addon_view_factory(qs=Addon.objects.valid)

THEMES_LIMIT = 20


def user_view(f):
    @functools.wraps(f)
    def wrapper(request, user_id, *args, **kw):
        """Provides a user object given a user ID or username."""
        if user_id.isdigit():
            key = 'id'
        else:
            key = 'username'
            # If the username is `me` then show the current user's profile.
            if (user_id == 'me' and request.amo_user and
                request.amo_user.username):
                user_id = request.amo_user.username
        user = get_object_or_404(UserProfile, **{key: user_id})
        return f(request, user, *args, **kw)
    return wrapper


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


@user_view
def confirm(request, user, token):
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


@user_view
def confirm_resend(request, user):
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
        form = forms.UserEditForm(instance=amouser)
    return jingo.render(request, 'users/edit.html',
                        {'form': form, 'amouser': amouser, 'webapp': False})


@write
@login_required
@permission_required('Users', 'Edit')
@user_view
def admin_edit(request, user):
    if request.method == 'POST':
        form = forms.AdminUserEditForm(request.POST, request.FILES,
                                       request=request, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, _('Profile Updated'))
            return http.HttpResponseRedirect(reverse('zadmin.index'))
    else:
        form = forms.AdminUserEditForm(instance=user)
    return jingo.render(request, 'users/edit.html',
                        {'form': form, 'amouser': user})


@user_view
def emailchange(request, user, token, hash):
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

    if not is_safe_url(url, host=request.get_host()):
        log.info(u'Unsafe redirect to %s' % url)
        url = settings.LOGIN_REDIRECT_URL

    domain = gets.get('domain', None)
    if domain in settings.VALID_LOGIN_REDIRECTS.keys():
        url = settings.VALID_LOGIN_REDIRECTS[domain] + url

    gets['to'] = url
    request.GET = gets
    return request


def browserid_authenticate(request, assertion, is_mobile=False,
                           browserid_audience=get_audience):
    """
    Verify a BrowserID login attempt. If the BrowserID assertion is
    good, but no account exists, create one.

    """
    url = settings.BROWSERID_VERIFICATION_URL

    # We must always force the Firefox OS identity provider. This is because
    # we are sometimes allowing unverified assertions and you can't mix that
    # feature with bridged IdPs. See bug 910938.
    extra_params = {}
    if settings.UNVERIFIED_ISSUER:
        extra_params['experimental_forceIssuer'] = settings.UNVERIFIED_ISSUER

    if is_mobile:
        # When persona is running in a mobile OS then we can allow unverified
        # assertions.
        url = settings.NATIVE_BROWSERID_VERIFICATION_URL
        extra_params['experimental_allowUnverified'] = 'true'

    log.debug('Verifying Persona at %s, audience: %s, '
              'extra_params: %s' % (url, browserid_audience, extra_params))
    result = verify(assertion, browserid_audience,
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
        # Added due to bug 905984. It's possible to have a UserProfile
        # that has no corresponding User object.
        if profile.user is None:
            profile.create_django_user(
                backend='django_browserid.auth.BrowserIDBackend')
        if profile.is_verified and not verified:
            # An attempt to log in to a verified address with an unverified
            # assertion is a very bad thing. Don't let that happen.
            log.debug('Verified user %s attempted to log in with an '
                      'unverified assertion!' % profile)
            return None, _('Please use the verified email for this account.')
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
def browserid_login(request, browserid_audience=None):
    msg = ''
    if waffle.switch_is_active('browserid-login'):
        if request.user.is_authenticated():
            # If username is different, maybe sign in as new user?
            return http.HttpResponse(status=200)
        try:
            is_mobile = bool(int(request.POST.get('is_mobile', 0)))
        except ValueError:
            is_mobile = False
        with statsd.timer('auth.browserid.verify'):
            profile, msg = browserid_authenticate(
                request, request.POST['assertion'],
                is_mobile=is_mobile,
                browserid_audience=browserid_audience or get_audience(request))
        if profile is not None:
            auth.login(request, profile.user)
            profile.log_login_attempt(True)
            return http.HttpResponse(status=200)
    else:
        msg = 'browserid-login waffle switch is not enabled'
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


@user_view
def profile(request, user):
    # Temporary until we decide we want user profile pages.
    if settings.MARKETPLACE:
        raise http.Http404

    webapp = False

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

    addons = []
    personas = []
    limited_personas = False
    if user.is_developer:
        addons = user.addons.reviewed().exclude(type=amo.ADDON_WEBAPP).filter(
            addonuser__user=user, addonuser__listed=True)

        personas = addons.filter(type=amo.ADDON_PERSONA).order_by(
            '-persona__popularity')
        if personas.count() > THEMES_LIMIT:
            limited_personas = True
            personas = personas[:THEMES_LIMIT]

        addons = addons.exclude(type=amo.ADDON_PERSONA).order_by(
            '-weekly_downloads')
        addons = amo.utils.paginate(request, addons, 5)

    # Don't show marketplace reviews for AMO (since that would break).
    reviews = list(user.reviews.exclude(addon__type=amo.ADDON_WEBAPP))

    data = {'profile': user, 'own_coll': own_coll, 'reviews': reviews,
            'fav_coll': fav_coll, 'edit_any_user': edit_any_user,
            'addons': addons, 'own_profile': own_profile,
            'personas': personas, 'limited_personas': limited_personas,
            'THEMES_LIMIT': THEMES_LIMIT}
    if not own_profile:
        data['abuse_form'] = AbuseForm(request=request)

    return jingo.render(request, 'users/profile.html', data)


@user_view
def themes(request, user, category=None):
    cats = Category.objects.filter(type=amo.ADDON_PERSONA)

    ctx = {
        'profile': user,
        'categories': order_by_translation(cats, 'name'),
        'search_cat': 'themes'
    }

    if user.is_artist:
        base = user.addons.reviewed().filter(type=amo.ADDON_PERSONA,
            addonuser__user=user, addonuser__listed=True)

        if category:
            qs = cats.filter(slug=category)
            ctx['category'] = cat = get_list_or_404(qs)[0]
            base = base.filter(categories__id=cat.id)

    else:
        base = Addon.objects.none()

    filter_ = PersonasFilter(request, base, key='sort',
                             default='popular')
    addons = amo.utils.paginate(request, filter_.qs, 30,
                                count=base.count())

    ctx.update({
        'addons': addons,
        'filter': filter_,
        'sorting': filter_.field,
        'sort_opts': filter_.opts
    })

    return jingo.render(request, 'browse/personas/grid.html', ctx)


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
@user_view
def report_abuse(request, user):
    form = AbuseForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        send_abuse_report(request, user, form.cleaned_data['text'])
        messages.success(request, _('User reported.'))
    else:
        return jingo.render(request, 'users/report_abuse_full.html',
                            {'profile': user, 'abuse_form': form, })
    return redirect(user.get_url_path())


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
