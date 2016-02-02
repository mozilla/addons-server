import base64
import functools
import logging
from collections import namedtuple

from django.conf import settings
from django.contrib.auth import login
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.utils.http import is_safe_url

from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView
from waffle.decorators import waffle_switch

from . import verify
from api.jwt_auth.views import JWTProtectedView
from users.models import UserProfile
from accounts.serializers import AccountSourceSerializer, UserProfileSerializer

log = logging.getLogger('accounts')

STUB_FXA_USER = namedtuple('FxAUser', ['source'])('fxa')


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
        user.update(fxa_id=identity['uid'], email=identity['email'])
    log.info('Logging in user {} from FxA'.format(user))
    login(request, user)


def with_user(fn):
    @functools.wraps(fn)
    def inner(self, request):
        data = request.GET if request.method == 'GET' else request.DATA
        state_parts = data.get('state', '').split(':', 1)
        state = state_parts[0]
        if 'code' not in data:
            log.info('No code provided.')
            return Response({'error': 'No code provided.'}, status=422)
        elif (not request.session.get('fxa_state') or
                request.session['fxa_state'] != state):
            log.info('State mismatch. URL: {url} Session: {session}'.format(
                url=data.get('state'),
                session=request.session.get('fxa_state'),
            ))
            return Response({'error': 'State mismatch.'}, status=400)

        try:
            identity = verify.fxa_identify(data['code'],
                                           config=settings.FXA_CONFIG)
        except verify.IdentificationError:
            log.info('Profile not found. Code: {}'.format(data['code']))
            return Response({'error': 'Profile not found.'}, status=401)
        else:
            identity_user = find_user(identity)
            if request.user.is_authenticated():
                if identity_user is not None and identity_user != request.user:
                    log.info('Conflict finding user during FxA login. '
                             'request.user: {}, identity_user: {}'.format(
                                 request.user.pk, identity_user.pk))
                    return Response({'error': 'User mismatch.'}, status=422)
                elif request.user.fxa_migrated():
                    log.info('User already migrated. '
                             'request.user: {}, identity_user: {}'.format(
                                 request.user, identity_user))
                    return Response(
                        {'error': 'User already migrated.'}, status=422)
                else:
                    user = request.user
            else:
                user = identity_user
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
            return fn(self, request, user=user, identity=identity,
                      next_path=next_path)
    return inner


class LoginView(APIView):

    @waffle_switch('fxa-auth')
    @with_user
    def post(self, request, user, identity, next_path):
        if user is None:
            return Response({'error': 'User does not exist.'}, status=422)
        else:
            login_user(request, user, identity)
            return Response({'email': identity['email']})


class RegisterView(APIView):

    @waffle_switch('fxa-auth')
    @with_user
    def post(self, request, user, identity, next_path):
        if user is not None:
            return Response({'error': 'That account already exists.'},
                            status=422)
        else:
            user = register_user(request, identity)
            return Response({'email': user.email})


class AuthenticateView(APIView):

    @waffle_switch('fxa-auth')
    @with_user
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
