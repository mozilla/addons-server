import base64
import functools
import logging
import os

from django.conf import settings
from django.contrib.auth import login
from django.core.urlresolvers import reverse
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.utils.encoding import force_bytes
from django.utils.http import is_safe_url
from django.utils.html import format_html
from django.utils.translation import ugettext_lazy as _

from rest_framework import generics
from rest_framework.authentication import SessionAuthentication
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from rest_framework_jwt.settings import api_settings as jwt_api_settings
from waffle.decorators import waffle_switch

from olympia.access.models import GroupUser
from olympia.amo import messages
from olympia.amo.decorators import write
from olympia.amo.utils import urlparams
from olympia.api.authentication import JWTKeyAuthentication
from olympia.api.permissions import GroupPermission
from olympia.users.models import UserProfile

from . import verify
from .serializers import AccountSuperCreateSerializer, UserProfileSerializer
from .utils import fxa_login_url, generate_fxa_state

log = logging.getLogger('accounts')

ERROR_AUTHENTICATED = 'authenticated'
ERROR_NO_CODE = 'no-code'
ERROR_NO_PROFILE = 'no-profile'
ERROR_NO_USER = 'no-user'
ERROR_STATE_MISMATCH = 'state-mismatch'
ERROR_USER_MISMATCH = 'user-mismatch'
ERROR_STATUSES = {
    ERROR_AUTHENTICATED: 400,
    ERROR_NO_CODE: 422,
    ERROR_NO_PROFILE: 401,
    ERROR_STATE_MISMATCH: 400,
    ERROR_USER_MISMATCH: 422,
}
LOGIN_ERROR_MESSAGES = {
    ERROR_AUTHENTICATED: _(u'You are already logged in.'),
    ERROR_NO_CODE:
        _(u'Your log in attempt could not be parsed. Please try again.'),
    ERROR_NO_PROFILE:
        _(u'Your Firefox Account could not be found. Please try again.'),
    ERROR_STATE_MISMATCH: _(u'You could not be logged in. Please try again.'),
    ERROR_USER_MISMATCH:
        _(u'Your Firefox Account already exists on this site.'),
}


def safe_redirect(url, action):
    if not is_safe_url(url):
        url = reverse('home')
    log.info(u'Redirecting after {} to: {}'.format(action, url))
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


def update_user(user, identity):
    """Update a user's info from FxA if needed."""
    if (user.fxa_id != identity['uid'] or
            user.email != identity['email']):
        log.info(
            'Updating user info from FxA for {pk}. Old {old_email} {old_uid} '
            'New {new_email} {new_uid}'.format(
                pk=user.pk, old_email=user.email, old_uid=user.fxa_id,
                new_email=identity['email'], new_uid=identity['uid']))
        user.update(fxa_id=identity['uid'], email=identity['email'])


def login_user(request, user, identity):
    update_user(user, identity)
    log.info('Logging in user {} from FxA'.format(user))
    user.log_login_attempt(True)
    login(request, user)


def fxa_error_message(message):
    login_help_url = (
        'https://support.mozilla.org/kb/access-your-add-ons-firefox-accounts')
    return format_html(
        u'{error} <a href="{url}">{help_text}</a>',
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
            next_path = base64.urlsafe_b64decode(
                force_bytes(encoded_path)).decode('utf-8')
        except TypeError:
            log.info('Error decoding next_path {}'.format(
                encoded_path))
            pass
    if not is_safe_url(next_path):
        next_path = None
    return next_path


def with_user(format, config=None):

    def outer(fn):
        @functools.wraps(fn)
        @write
        def inner(self, request):
            if config is None:
                fxa_config = (
                    settings.FXA_CONFIG[settings.DEFAULT_FXA_CONFIG_NAME])
            else:
                fxa_config = config

            if request.method == 'GET':
                data = request.query_params
            else:
                data = request.data

            state_parts = data.get('state', '').split(':', 1)
            state = state_parts[0]
            next_path = parse_next_path(state_parts)
            if not data.get('code'):
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
            elif request.user.is_authenticated():
                return render_error(
                    request, ERROR_AUTHENTICATED, next_path=None,
                    format=format)
            try:
                identity = verify.fxa_identify(data['code'], config=fxa_config)
            except verify.IdentificationError:
                log.info('Profile not found. Code: {}'.format(data['code']))
                return render_error(
                    request, ERROR_NO_PROFILE, next_path=next_path,
                    format=format)
            else:
                return fn(
                    self, request, user=find_user(identity), identity=identity,
                    next_path=next_path)
        return inner
    return outer


def add_api_token_to_response(response, user, set_cookie=True):
    # Generate API token and add it to the json response.
    payload = jwt_api_settings.JWT_PAYLOAD_HANDLER(user)
    token = jwt_api_settings.JWT_ENCODE_HANDLER(payload)
    if hasattr(response, 'data'):
        response.data['token'] = token
    if set_cookie:
        # Also include the API token in a session cookie, so that it is
        # available for universal frontend apps.
        response.set_cookie(
            'jwt_api_auth_token',
            token,
            max_age=settings.SESSION_COOKIE_AGE or None,
            secure=settings.SESSION_COOKIE_SECURE or None,
            httponly=settings.SESSION_COOKIE_HTTPONLY or None)

    return response


class FxAConfigMixin(object):

    def get_config_name(self, request):
        return request.GET.get('config', self.DEFAULT_FXA_CONFIG_NAME)

    def get_allowed_configs(self):
        return getattr(
            self, 'ALLOWED_FXA_CONFIGS', [self.DEFAULT_FXA_CONFIG_NAME])

    def get_fxa_config(self, request):
        config_name = self.get_config_name(request)
        if config_name in self.get_allowed_configs():
            return settings.FXA_CONFIG[config_name]
        log.info('Using default FxA config instead of {}'.format(config_name))
        return settings.FXA_CONFIG[self.DEFAULT_FXA_CONFIG_NAME]


class LoginStartBaseView(FxAConfigMixin, APIView):

    def get(self, request):
        request.session.setdefault('fxa_state', generate_fxa_state())
        return HttpResponseRedirect(
            fxa_login_url(
                config=self.get_fxa_config(request),
                state=request.session['fxa_state'],
                next_path=request.GET.get('to'),
                action=request.GET.get('action', 'signin')))


class LoginStartView(LoginStartBaseView):
    DEFAULT_FXA_CONFIG_NAME = settings.DEFAULT_FXA_CONFIG_NAME
    ALLOWED_FXA_CONFIGS = settings.ALLOWED_FXA_CONFIGS


class LoginBaseView(FxAConfigMixin, APIView):

    def post(self, request):
        config = self.get_fxa_config(request)

        @with_user(format='json', config=config)
        def _post(self, request, user, identity, next_path):
            if user is None:
                return Response({'error': ERROR_NO_USER}, status=422)
            else:
                update_user(user, identity)
                response = Response({'email': identity['email']})
                add_api_token_to_response(response, user, set_cookie=False)
                log.info('Logging in user {} from FxA'.format(user))
                return response
        return _post(self, request)

    def options(self, request):
        return Response()


class LoginView(LoginBaseView):
    DEFAULT_FXA_CONFIG_NAME = settings.DEFAULT_FXA_CONFIG_NAME
    ALLOWED_FXA_CONFIGS = settings.ALLOWED_FXA_CONFIGS


class RegisterView(APIView):
    authentication_classes = (SessionAuthentication,)

    @with_user(format='json')
    def post(self, request, user, identity, next_path):
        if user is not None:
            return Response({'error': 'That account already exists.'},
                            status=422)
        else:
            user = register_user(request, identity)
            response = Response({'email': user.email})
            add_api_token_to_response(response, user)
            return response


class AuthenticateView(APIView):
    authentication_classes = (SessionAuthentication,)

    @with_user(format='html')
    def get(self, request, user, identity, next_path):
        if user is None:
            register_user(request, identity)
            return safe_redirect(reverse('users.edit'), 'register')
        else:
            login_user(request, user, identity)
            response = safe_redirect(next_path, 'login')
            add_api_token_to_response(response, user)
            return response


class ProfileView(generics.RetrieveAPIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def retrieve(self, request, *args, **kw):
        return Response(self.get_serializer(request.user).data)


class AccountViewSet(RetrieveModelMixin, GenericViewSet):
    queryset = UserProfile.objects.all()

    def retrieve(self, request, *args, **kwargs):
        # See https://github.com/mozilla/addons-server/issues/3138 ; be careful
        # when implementing it, we don't want to list users, only retrieve them
        # and eventually modify them through this ViewSet.
        raise NotImplementedError


class AccountSuperCreate(APIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = [
        IsAuthenticated, GroupPermission('Accounts', 'SuperCreate')]

    @waffle_switch('super-create-accounts')
    def post(self, request):
        serializer = AccountSuperCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'errors': serializer.errors},
                            status=422)

        data = serializer.data

        group = serializer.validated_data.get('group', None)
        user_token = os.urandom(4).encode('hex')
        username = data.get('username', 'super-created-{}'.format(user_token))
        fxa_id = data.get('fxa_id', None)
        email = data.get('email', '{}@addons.mozilla.org'.format(username))

        user = UserProfile.objects.create(
            username=username,
            email=email,
            fxa_id=fxa_id,
            display_name='Super Created {}'.format(user_token),
            is_verified=True,
            notes='auto-generated from API')
        user.save()

        if group:
            GroupUser.objects.create(user=user, group=group)

        login(request, user)
        request.session.save()

        log.info(u'API user {api_user} created and logged in a user from '
                 u'the super-create API: user_id: {user.pk}; '
                 u'user_name: {user.username}; fxa_id: {user.fxa_id}; '
                 u'group: {group}'
                 .format(user=user, api_user=request.user, group=group))

        cookie = {
            'name': settings.SESSION_COOKIE_NAME,
            'value': request.session.session_key,
        }
        cookie['encoded'] = '{name}={value}'.format(**cookie)

        return Response({
            'user_id': user.pk,
            'username': user.username,
            'email': user.email,
            'display_name': user.display_name,
            'groups': list((g.pk, g.name, g.rules) for g in user.groups.all()),
            'fxa_id': user.fxa_id,
            'session_cookie': cookie,
        }, status=201)
