import functools
from functools import partial

from django import http
from django.conf import settings
from django.contrib import auth
from django.contrib.auth.tokens import default_token_generator
from django.db.transaction import non_atomic_requests
from django.shortcuts import (get_list_or_404, get_object_or_404, redirect,
                              render)
from django.template import Context, loader
from django.utils.http import is_safe_url, urlsafe_base64_decode
from django.views.decorators.cache import never_cache
from django.utils.translation import ugettext as _

import commonware.log
from mobility.decorators import mobile_template
from session_csrf import anonymous_csrf, anonymous_csrf_exempt

from olympia import amo
from olympia.users import notifications as notifications
from olympia.abuse.models import send_abuse_report
from olympia.access import acl
from olympia.access.middleware import ACLMiddleware
from olympia.addons.decorators import addon_view_factory
from olympia.addons.models import Addon, Category
from olympia.amo import messages
from olympia.amo.decorators import (
    json_view, login_required, permission_required,
    post_required, write)
from olympia.amo.forms import AbuseForm
from olympia.amo.urlresolvers import get_url_prefix, reverse
from olympia.amo.utils import escape_all, send_mail, urlparams
from olympia.bandwagon.models import Collection
from olympia.browse.views import PersonasFilter
from olympia.translations.query import order_by_translation
from olympia.users.models import UserNotification

from . import forms, tasks
from .models import UserProfile
from .signals import logged_out
from .utils import EmailResetCode, UnsubscribeCode


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
            if (user_id == 'me' and request.user and
                    request.user.username):
                user_id = request.user.username
        user = get_object_or_404(UserProfile, **{key: user_id})
        return f(request, user, *args, **kw)
    return wrapper


@login_required(redirect=False)
@json_view
@non_atomic_requests
def ajax(request):
    """Query for a user matching a given email."""

    if 'q' not in request.GET:
        raise http.Http404()

    data = {'status': 0, 'message': ''}

    email = request.GET.get('q', '').strip()

    if not email:
        data.update(message=_('An email address is required.'))
        return data

    user = UserProfile.objects.filter(email=email)

    msg = _('A user with that email address does not exist.')

    if user:
        data.update(status=1, id=user[0].id, name=user[0].name)
    else:
        data['message'] = msg

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

    msg = _(u'An email has been sent to your address to confirm '
            u'your account. Before you can log in, you have to activate '
            u'your account by clicking on the link provided in this '
            u'email.')
    messages.info(request, _('Confirmation Email Sent'), msg)

    return redirect('users.login')


@login_required
def delete(request):
    amouser = request.user
    if request.method == 'POST':
        form = forms.UserDeleteForm(request.POST, request=request)
        if form.is_valid():
            messages.success(request, _('Profile Deleted'))
            amouser.anonymize()
            logout(request)
            form = None
            return http.HttpResponseRedirect(reverse('users.login'))
    else:
        form = forms.UserDeleteForm(request=request)

    return render(request, 'users/delete.html',
                  {'form': form, 'amouser': amouser})


@login_required
def delete_photo(request, user_id):
    not_mine = str(request.user.id) != user_id
    if (not_mine and not acl.action_allowed(request, 'Users', 'Edit')):
        return http.HttpResponseForbidden()

    user = UserProfile.objects.get(id=user_id)

    if request.method == 'POST':
        user.picture_type = ''
        user.save()
        log.debug(u'User (%s) deleted photo' % user)
        tasks.delete_photo.delay(user.picture_path)
        messages.success(request, _('Photo Deleted'))
        redirect = (
            reverse('users.admin_edit', kwargs={'user_id': user.id})
            if not_mine else reverse('users.edit')
        )
        return http.HttpResponseRedirect(redirect + '#user-profile')

    return render(request, 'users/delete_photo.html', dict(user=user))


@write
@login_required
def edit(request):
    # Don't use request.user since it has too much caching.
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
                log.info(u"User (%(user)s) has requested email change from "
                         u"(%(mail1)s) to (%(mail2)s)" % l)
                messages.info(
                    request, _('Email Confirmation Sent'),
                    _(u'An email has been sent to {0} to confirm your new '
                      u'email address. For the change to take effect, you '
                      u'need to click on the link provided in this email. '
                      u'Until then, you can keep logging in with your '
                      u'current email address.').format(amouser.email))

                token, hash_ = EmailResetCode.create(amouser.id, amouser.email)
                url = '%s%s' % (settings.SITE_URL,
                                reverse('users.emailchange',
                                        args=[amouser.id, token, hash_]))
                t = loader.get_template('users/email/emailchange.ltxt')
                c = {'domain': settings.DOMAIN, 'url': url}
                send_mail(
                    _('Please confirm your email address '
                      'change at %s' % settings.DOMAIN),
                    t.render(Context(c)), None, [amouser.email],
                    use_blacklist=False, real_email=True)

                # Reset the original email back.  We aren't changing their
                # address until they confirm the new one
                amouser.email = original_email
            form.save()
            return redirect('users.edit')
        else:

            messages.error(
                request,
                _('Errors Found'),
                _('There were errors in the changes you made. Please correct '
                  'them and resubmit.'))
    else:
        form = forms.UserEditForm(instance=amouser, request=request)
    return render(request, 'users/edit.html',
                  {'form': form, 'amouser': amouser})


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
        form = forms.AdminUserEditForm(instance=user, request=request)
    return render(request, 'users/edit.html', {'form': form, 'amouser': user})


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
                     u"attempted to change email address for user (%s)") %
                    (_uid, user))
        return http.HttpResponse(status=400)

    if UserProfile.objects.filter(email=newemail).exists():
        log.warning((u"[Tampering] User (%s) tries to change his email to "
                     u"an existing account with the same email address (%s)") %
                    (user, newemail))
        return http.HttpResponse(status=400)

    user.email = newemail
    user.save()

    l = {'user': user, 'newemail': newemail}
    log.info(u"User (%(user)s) confirmed new email address (%(newemail)s)" % l)
    messages.success(
        request, _('Your email address was changed successfully'),
        _(u'From now on, please use {0} to log in.').format(newemail))

    return http.HttpResponseRedirect(reverse('users.edit'))


def _clean_next_url(request):
    gets = request.GET.copy()
    url = gets.get('to', settings.LOGIN_REDIRECT_URL)

    if not is_safe_url(url):
        log.info(u'Unsafe redirect to %s' % url)
        url = settings.LOGIN_REDIRECT_URL

    domain = gets.get('domain', None)
    if domain in settings.VALID_LOGIN_REDIRECTS.keys():
        url = settings.VALID_LOGIN_REDIRECTS[domain] + url

    gets['to'] = url
    request.GET = gets
    return request


@anonymous_csrf
@mobile_template('users/{mobile/}login_modal.html')
def login_modal(request, template=None):
    return _login(request, template=template)


@anonymous_csrf
@mobile_template('users/{mobile/}login.html')
def login(request, template=None):
    return _login(request, template=template)


def _login(request, template=None, data=None, dont_redirect=False):
    data = data or {}
    # In case we need it later.  See below.
    get_copy = request.GET.copy()

    if 'to' in request.GET:
        request = _clean_next_url(request)

    if request.user.is_authenticated():
        return http.HttpResponseRedirect(
            request.GET.get('to', settings.LOGIN_REDIRECT_URL))

    data['login_source_form'] = not request.POST

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
            log.info(
                'Authentication failure, username invalid (%s)'
                % request.POST['username'])
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

        request.GET = get_copy
        request = _clean_next_url(request)
        next_path = request.GET['to']
        if next_path == '/':
            next_path = None
        next_path = urlparams(reverse('users.migrate'), to=next_path)
        r = http.HttpResponseRedirect(next_path)

        # Succsesful log in according to django.  Now we do our checks.  I do
        # the checks here instead of the form's clean() because I want to use
        # the messages framework and it's not available in the request there.
        if user.deleted:
            logout(request)
            log.warning(u'Attempt to log in with deleted account (%s)' % user)
            messages.error(request, _('Wrong email address or password!'))
            data.update({'form': partial_form()})
            user.log_login_attempt(False)
            log.info(
                'Authentication Failure, account is deactivated (%s)'
                % request.user)
            return render(request, template, data)

        if user.confirmationcode:
            logout(request)
            log.info(u'Attempt to log in with unconfirmed account (%s)' % user)
            msg1 = _(u'A link to activate your user account was sent by email '
                     u'to your address {0}. You have to click it before you '
                     u'can log in.').format(user.email)
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
            return render(request, template, data)

        rememberme = request.POST.get('rememberme', None)
        if rememberme:
            request.session.set_expiry(settings.SESSION_COOKIE_AGE)
            log.debug(
                u'User (%s) logged in successfully with "remember me" set' %
                user)

        login_status = True

        if dont_redirect:
            # We're recalling the middleware to re-initialize user
            ACLMiddleware().process_request(request)
            r = render(request, template, data)

    if login_status is not None:
        user.log_login_attempt(login_status)
        log.info(
            'Authentication Failure, incorrect password (%s)'
            % request.POST['username'])

    return r


def logout(request):
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
@non_atomic_requests
def profile(request, user):
    # Get user's own and favorite collections, if they allowed that.
    own_coll = fav_coll = []
    if user.display_collections:
        own_coll = (Collection.objects.listed().filter(author=user)
                    .order_by('-created'))[:10]
    if user.display_collections_fav:
        fav_coll = (Collection.objects.listed()
                    .filter(following__user=user)
                    .order_by('-following__created'))[:10]

    edit_any_user = acl.action_allowed(request, 'Users', 'Edit')
    own_profile = (request.user.is_authenticated() and
                   request.user.id == user.id)

    addons = []
    personas = []
    limited_personas = False
    if user.is_developer:
        addons = user.addons.reviewed().filter(
            addonuser__user=user, addonuser__listed=True)

        personas = addons.filter(type=amo.ADDON_PERSONA).order_by(
            '-persona__popularity')
        if personas.count() > THEMES_LIMIT:
            limited_personas = True
            personas = personas[:THEMES_LIMIT]

        addons = addons.exclude(type=amo.ADDON_PERSONA).order_by(
            '-weekly_downloads')
        addons = amo.utils.paginate(request, addons, 5)

    reviews = amo.utils.paginate(request, user.reviews.all())

    data = {'profile': user, 'own_coll': own_coll, 'reviews': reviews,
            'fav_coll': fav_coll, 'edit_any_user': edit_any_user,
            'addons': addons, 'own_profile': own_profile,
            'personas': personas, 'limited_personas': limited_personas,
            'THEMES_LIMIT': THEMES_LIMIT}
    if not own_profile:
        data['abuse_form'] = AbuseForm(request=request)

    return render(request, 'users/profile.html', data)


@user_view
@non_atomic_requests
def themes(request, user, category=None):
    cats = Category.objects.filter(type=amo.ADDON_PERSONA)

    ctx = {
        'profile': user,
        'categories': order_by_translation(cats, 'name'),
        'search_cat': 'themes'
    }

    if user.is_artist:
        base = user.addons.reviewed().filter(
            type=amo.ADDON_PERSONA,
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

    return render(request, 'browse/personas/grid.html', ctx)


@anonymous_csrf_exempt
@user_view
def report_abuse(request, user):
    form = AbuseForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        send_abuse_report(request, user, form.cleaned_data['text'])
        messages.success(request, _('User reported.'))
    else:
        return render(request, 'users/report_abuse_full.html',
                      {'profile': user, 'abuse_form': form})
    return redirect(user.get_url_path())


@post_required
@user_view
def remove_locale(request, user):
    """Remove a locale from the user's translations."""
    POST = request.POST
    if 'locale' in POST and POST['locale'] != settings.LANGUAGE_CODE:
        user.remove_locale(POST['locale'])
        return http.HttpResponse()
    return http.HttpResponseBadRequest()


@never_cache
@anonymous_csrf
def password_reset_confirm(request, uidb64=None, token=None):
    """
    Pulled from django contrib so that we can add user into the form
    so then we can show relevant messages about the user.
    """
    assert uidb64 is not None and token is not None
    user = None
    try:
        uid_int = urlsafe_base64_decode(uidb64)
        user = UserProfile.objects.get(id=uid_int)
    except (ValueError, UserProfile.DoesNotExist, TypeError):
        pass

    if user is not None and user.fxa_migrated():
        migrated = True
        validlink = False
        form = None
    elif user is not None and default_token_generator.check_token(user, token):
        migrated = False
        validlink = True
        if request.method == 'POST':
            form = forms.SetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()
                log.info('Password Changed (%s)' % user.username)
                return redirect(reverse('django.contrib.auth.'
                                        'views.password_reset_complete'))
        else:
            form = forms.SetPasswordForm(user)
    else:
        migrated = False
        validlink = False
        form = None

    return render(request, 'users/pwreset_confirm.html',
                  {'form': form, 'validlink': validlink, 'migrated': migrated})


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
            UserNotification.update_or_create(
                update={'enabled': False},
                user=user, notification_id=perm_setting.id)
            perm_settings = [perm_setting]
    else:
        unsubscribed = False
        email = ''

    return render(request, 'users/unsubscribe.html',
                  {'unsubscribed': unsubscribed, 'email': email,
                   'perm_settings': perm_settings})


@mobile_template('users/{mobile/}fxa_migration.html')
def migrate(request, template=None):
    next_path = request.GET.get('to')
    if not next_path or not is_safe_url(next_path):
        next_path = reverse('home')
    if not request.user.is_authenticated() or request.user.fxa_migrated():
        return redirect(next_path)
    else:
        return render(request, template, {'to': next_path})
