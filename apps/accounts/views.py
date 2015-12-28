import functools
import logging
from collections import namedtuple

from django.conf import settings
from django.contrib.auth import login
from django.db.models import Q
from django.http import HttpResponseRedirect

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
        if 'code' not in data:
            return Response({'error': 'No code provided.'}, status=422)
        elif ('fxa_state' not in request.session or
                request.session['fxa_state'] != data['state']):
            return Response({'error': 'State mismatch.'}, status=400)

        try:
            identity = verify.fxa_identify(data['code'],
                                           config=settings.FXA_CONFIG)
        except verify.IdentificationError:
            return Response({'error': 'Profile not found.'}, status=401)
        else:
            identity_user = find_user(identity)
            if request.user.is_authenticated():
                if identity_user is not None and identity_user != request.user:
                    log.info('Conflict finding user during FxA login. '
                             'request.user: {}, identity_user: {}'.format(
                                 request.user.pk, identity_user.pk))
                    return Response({'error': 'User mismatch.'}, status=422)
                elif request.user.fxa_id is not None:
                    return Response(
                        {'error': 'User already migrated.'}, status=422)
                else:
                    user = request.user
            else:
                user = identity_user
            return fn(self, request, user=user, identity=identity)
    return inner


class LoginView(APIView):

    @waffle_switch('fxa-auth')
    @with_user
    def post(self, request, user, identity):
        if user is None:
            return Response({'error': 'User does not exist.'}, status=422)
        else:
            login_user(request, user, identity)
            return Response({'email': identity['email']})


class RegisterView(APIView):

    @waffle_switch('fxa-auth')
    @with_user
    def post(self, request, user, identity):
        if user is not None:
            return Response({'error': 'That account already exists.'},
                            status=422)
        else:
            user = register_user(request, identity)
            return Response({'email': user.email})


class AuthorizeView(APIView):

    @waffle_switch('fxa-auth')
    @with_user
    def get(self, request, user, identity):
        if user is None:
            register_user(request, identity)
        else:
            login_user(request, user, identity)
        return HttpResponseRedirect('/')


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
