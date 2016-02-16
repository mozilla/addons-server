import base64
import functools
import logging
import os
from collections import namedtuple

from django.conf import settings
from django.contrib.auth import login
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.utils.http import is_safe_url
from django.utils.html import format_html

from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tower import ugettext_lazy as _
from waffle.decorators import waffle_switch

from olympia.amo import messages
from olympia.amo.utils import urlparams
from olympia.api.jwt_auth.views import JWTProtectedView
from olympia.api.permissions import GroupPermission
from olympia.users.models import UserProfile
from olympia.accounts.serializers import (
    AccountSourceSerializer, AccountSuperCreateSerializer,
    UserProfileSerializer)

from . import verify

log = logging.getLogger('accounts')

STUB_FXA_USER = namedtuple('FxAUser', ['source'])('fxa')

ERROR_NO_CODE = 'no-code'
ERROR_NO_PROFILE = 'no-profile'
ERROR_NO_USER = 'no-user'
ERROR_STATE_MISMATCH = 'state-mismatch'
ERROR_USER_MISMATCH = 'user-mismatch'
ERROR_USER_MIGRATED = 'user-migrated'
ERROR_STATUSES = {
    ERROR_NO_CODE: 422,
    ERROR_NO_PROFILE: 401,
    ERROR_STATE_MISMATCH: 400,
    ERROR_USER_MISMATCH: 422,
    ERROR_USER_MIGRATED: 422,
}
LOGIN_ERROR_MESSAGES = {
    ERROR_NO_CODE:
        _(u'Your log in attempt could not be parsed. Please try again.'),
    ERROR_NO_PROFILE:
        _(u'Your Firefox Account could not be found. Please try again.'),
    ERROR_STATE_MISMATCH: _(u'You could not be logged in. Please try again.'),
    ERROR_USER_MIGRATED:
        _(u'Your account has already been migrated to Firefox Accounts.'),
    ERROR_USER_MISMATCH:
        _(u'Your Firefox Account already exists on this site.'),
}


def safe_redirect(url, action):
    if not is_safe_url(url):
        url = reverse('home')
    log.info('Redirecting after {} to: {}'.format(action, url))
    return HttpResponseRedirect(url)


def find_user(identity):
    """Try to find a user for a Firefox Accounts profile. If the account
    hasn't been migrated we'll need to do the lookup by email but we should
    use the ID after that so check both. If we get multiple users we're in
    some weird state where the accounts need to be merged but that behaviour
    hasn't been defined so let it raise.
    """
    try:
        return UserProfile.objects.get(
            Q(fxa_id=identity['uid']) | Q(email=identity['email']))
    except UserProfile.DoesNotExist:
        return None
    except UserProfile.MultipleObjectsReturned:
        # This shouldn't happen, so let it raise.
        log.error(
            'Found multiple users for {email} and {uid}'.format(**identity))
        raise


def register_user(request, identity):
    user = UserProfile.objects.create_user(
        email=identity['email'], username=None, fxa_id=identity['uid'])
    log.info('Created user {} from FxA'.format(user))
    login(request, user)
    return user


def login_user(request, user, identity):
    if (user.fxa_id != identity['uid'] or
            user.email != identity['email']):
        log.info(
            'Updating user info from FxA for {pk}. Old {old_email} {old_uid} '
            'New {new_email} {new_uid}'.format(
                pk=user.pk, old_email=user.email, old_uid=user.fxa_id,
                new_email=identity['email'], new_uid=identity['uid']))
        if not user.fxa_migrated():
            messages.success(
                request,
                _(u'Great job!'),
                _(u'You can now log in to Add-ons with your Firefox Account.'),
                extra_tags='fxa')
        user.update(fxa_id=identity['uid'], email=identity['email'])
    log.info('Logging in user {} from FxA'.format(user))
    login(request, user)


def fxa_error_message(message):
    login_help_url = (
        'https://support.mozilla.org/kb/access-your-add-ons-firefox-accounts')
    return format_html(
        u'{error} <a href="{url}" target="_blank">{help_text}</a>',
        url=login_help_url, help_text=_(u'Need help?'),
        error=message)


def render_error(request, error, next_path=None, format=None):
    if format == 'json':
        status = ERROR_STATUSES.get(error, 422)
        return Response({'error': error}, status=status)
    else:
        if not is_safe_url(next_path):
            next_path = None
        messages.error(
            request, fxa_error_message(LOGIN_ERROR_MESSAGES[error]),
            extra_tags='fxa')
        if request.user.is_authenticated():
            redirect_view = 'users.migrate'
        else:
            redirect_view = 'users.login'
        return HttpResponseRedirect(
            urlparams(reverse(redirect_view), to=next_path))


def parse_next_path(state_parts):
    next_path = None
    if len(state_parts) == 2:
        # The = signs will be stripped off so we need to add them back
        # but it only cares if there are too few so add 4 of them.
        encoded_path = state_parts[1] + '===='
        try:
            next_path = base64.urlsafe_b64decode(str(encoded_path))
        except TypeError:
            log.info('Error decoding next_path {}'.format(
                encoded_path))
            pass
    if not is_safe_url(next_path):
        next_path = None
    return next_path


def with_user(format):
    def outer(fn):
        @functools.wraps(fn)
        def inner(self, request):
            data = request.GET if request.method == 'GET' else request.DATA
            state_parts = data.get('state', '').split(':', 1)
            state = state_parts[0]
            next_path = parse_next_path(state_parts)
            if 'code' not in data:
                log.info('No code provided.')
                return render_error(
                    request, ERROR_NO_CODE, next_path=next_path, format=format)
            elif (not request.session.get('fxa_state') or
                    request.session['fxa_state'] != state):
                log.info(
                    'State mismatch. URL: {url} Session: {session}'.format(
                        url=data.get('state'),
                        session=request.session.get('fxa_state'),
                    ))
                return render_error(
                    request, ERROR_STATE_MISMATCH, next_path=next_path,
                    format=format)

            try:
                identity = verify.fxa_identify(
                    data['code'], config=settings.FXA_CONFIG)
            except verify.IdentificationError:
                log.info('Profile not found. Code: {}'.format(data['code']))
                return render_error(
                    request, ERROR_NO_PROFILE, next_path=next_path,
                    format=format)
            else:
                identity_user = find_user(identity)
                if request.user.is_authenticated():
                    if (identity_user is not None
                            and identity_user != request.user):
                        log.info('Conflict finding user during FxA login. '
                                 'request.user: {}, identity_user: {}'.format(
                                     request.user.pk, identity_user.pk))
                        return render_error(
                            request, ERROR_USER_MISMATCH, next_path=next_path,
                            format=format)
                    elif request.user.fxa_migrated():
                        log.info('User already migrated. '
                                 'request.user: {}, identity_user: {}'.format(
                                     request.user, identity_user))
                        return render_error(
                            request, ERROR_USER_MIGRATED, next_path=next_path,
                            format=format)
                    else:
                        user = request.user
                else:
                    user = identity_user
                return fn(self, request, user=user, identity=identity,
                          next_path=next_path)
        return inner
    return outer


class LoginView(APIView):

    @waffle_switch('fxa-auth')
    @with_user(format='json')
    def post(self, request, user, identity, next_path):
        if user is None:
            return Response({'error': ERROR_NO_USER}, status=422)
        else:
            login_user(request, user, identity)
            return Response({'email': identity['email']})


class RegisterView(APIView):

    @waffle_switch('fxa-auth')
    @with_user(format='json')
    def post(self, request, user, identity, next_path):
        if user is not None:
            return Response({'error': 'That account already exists.'},
                            status=422)
        else:
            user = register_user(request, identity)
            return Response({'email': user.email})


class AuthenticateView(APIView):

    @waffle_switch('fxa-auth')
    @with_user(format='html')
    def get(self, request, user, identity, next_path):
        if user is None:
            register_user(request, identity)
            return safe_redirect(reverse('users.edit'), 'register')
        else:
            login_user(request, user, identity)
            return safe_redirect(next_path, 'login')


class ProfileView(JWTProtectedView, generics.RetrieveAPIView):
    serializer_class = UserProfileSerializer

    def retrieve(self, request, *args, **kw):
        return Response(self.get_serializer(request.user).data)


class AccountSourceView(generics.RetrieveAPIView):
    serializer_class = AccountSourceSerializer

    @waffle_switch('fxa-auth')
    def retrieve(self, request, *args, **kwargs):
        email = request.GET.get('email')
        try:
            user = UserProfile.objects.get(email=email)
        except UserProfile.DoesNotExist:
            # Use the stub FxA user with source='fxa' when the account doesn't
            # exist. This will make it more difficult to discover if an email
            # address has an account associated with it.
            user = STUB_FXA_USER
        return Response(self.get_serializer(user).data)


class AccountSuperCreate(JWTProtectedView):
    permission_classes = [
        IsAuthenticated, GroupPermission('Accounts', 'SuperCreate')]

    @waffle_switch('super-create-accounts')
    def post(self, request):
        serializer = AccountSuperCreateSerializer(data=request.DATA)
        if not serializer.is_valid():
            return Response({'errors': serializer.errors},
                            status=422)

        user_token = os.urandom(4).encode('hex')
        username = 'super-created-{}'.format(user_token)
        email = serializer.data['email']
        if not email:
            email = '{}@addons.mozilla.org'.format(username)
        password = os.urandom(16).encode('hex')

        user = UserProfile.objects.create(
            username=username,
            email=email,
            display_name='Super Created {}'.format(user_token),
            is_verified=True,
            confirmationcode='',
            notes='auto-generated from API')
        user.set_password(password)
        user.save()

        login(request, user)
        request.session.save()

        log.info(u'API user {api_user} created and logged in a user from '
                 u'the super-create API: user_id: {user.pk}; '
                 u'user_name: {user.username}'
                 .format(user=user, api_user=request.user))

        cookie = {
            'name': settings.SESSION_COOKIE_NAME,
            'value': request.session.session_key,
        }
        cookie['encoded'] = '{name}={value}'.format(**cookie)

        return Response({
            'user_id': user.pk,
            'username': user.username,
            'email': user.email,
            'session_cookie': cookie,
        }, status=201)
