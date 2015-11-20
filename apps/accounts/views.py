import functools
import logging

from django.conf import settings
from django.contrib.auth import login
from django.db.models import Q

from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView
from waffle.decorators import waffle_switch

from . import verify
from api.jwt_auth.views import JWTProtectedView
from users.models import UserProfile
from accounts.serializers import UserProfileSerializer

log = logging.getLogger('accounts')


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


def with_user(fn):
    @functools.wraps(fn)
    def inner(self, request):
        if 'code' not in request.DATA:
            return Response({'error': 'No code provided.'}, status=422)

        try:
            identity = verify.fxa_identify(request.DATA['code'],
                                           config=settings.FXA_CONFIG)
        except verify.IdentificationError:
            return Response({'error': 'Profile not found.'}, status=401)
        return fn(self, request, user=find_user(identity), identity=identity)
    return inner


class LoginView(APIView):

    @waffle_switch('fxa-auth')
    @with_user
    def post(self, request, user, identity):
        if user is None:
            return Response({'error': 'User does not exist.'}, status=422)
        else:
            if (user.fxa_id != identity['uid'] or
                    user.email != identity['email']):
                log.info(
                    'Updating user info from FxA. Old {old_email} {old_uid} '
                    'New {new_email} {new_uid}'.format(
                        old_email=user.email, old_uid=user.fxa_id,
                        new_email=identity['email'], new_uid=identity['uid']))
                user.update(fxa_id=identity['uid'], email=identity['email'])
            log.info('Logging in user {} from FxA'.format(user))
            login(request, user)
            return Response({'email': identity['email']})


class ProfileView(JWTProtectedView, generics.RetrieveAPIView):
    serializer_class = UserProfileSerializer

    def retrieve(self, request, *args, **kw):
        return Response(self.get_serializer(request.user).data)


class RegisterView(APIView):

    @waffle_switch('fxa-auth')
    @with_user
    def post(self, request, user, identity):
        if user is not None:
            return Response({'error': 'That account already exists.'},
                            status=422)
        else:
            user = UserProfile.objects.create_user(
                email=identity['email'], username=None, fxa_id=identity['uid'])
            log.info('Created user {} from FxA'.format(user))
            login(request, user)
            return Response({'email': user.email})
