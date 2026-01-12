import base64
import binascii
import functools
import os
import time
from urllib.parse import quote_plus

from django.conf import settings
from django.contrib.auth import login, logout
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.encoding import force_bytes, force_str
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache

import jwt
import requests
from corsheaders.conf import conf as corsheaders_conf
from corsheaders.middleware import (
    ACCESS_CONTROL_ALLOW_CREDENTIALS,
    ACCESS_CONTROL_ALLOW_HEADERS,
    ACCESS_CONTROL_ALLOW_METHODS,
    ACCESS_CONTROL_ALLOW_ORIGIN,
    ACCESS_CONTROL_MAX_AGE,
)
from django_statsd.clients import statsd
from rest_framework import exceptions, serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import (
    DestroyModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
)
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_204_NO_CONTENT
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from waffle.decorators import waffle_switch

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.access.models import GroupUser
from olympia.activity.models import ActivityLog
from olympia.amo.decorators import use_primary_db
from olympia.amo.reverse import get_url_prefix
from olympia.amo.utils import fetch_subscribed_newsletters, is_safe_url, use_fake_fxa
from olympia.api.authentication import (
    JWTKeyAuthentication,
    SessionIDAuthentication,
    UnsubscribeTokenAuthentication,
)
from olympia.api.permissions import AnyOf, ByHttpMethod, GroupPermission
from olympia.users.models import UserNotification, UserProfile
from olympia.users.notifications import (
    NOTIFICATIONS_COMBINED,
    REMOTE_NOTIFICATIONS_BY_BASKET_ID,
)

from . import verify
from .serializers import (
    AccountSuperCreateSerializer,
    FullUserProfileSerializer,
    MinimalUserProfileSerializer,
    SelfUserProfileSerializer,
    UserNotificationSerializer,
)
from .tasks import clear_sessions_event, delete_user_event, primary_email_change_event
from .utils import (
    get_fxa_config,
    get_fxa_config_name,
    redirect_for_login,
    redirect_for_login_with_2fa_enforced,
)


log = olympia.core.logger.getLogger('accounts')

ERROR_AUTHENTICATED = 'authenticated'
ERROR_NO_CODE = 'no-code'
ERROR_NO_PROFILE = 'no-profile'
ERROR_NO_USER = 'no-user'
ERROR_STATE_MISMATCH = 'state-mismatch'
ERROR_FXA_ERROR = 'error-fxa'
ERROR_STATUSES = {
    ERROR_AUTHENTICATED: 400,
    ERROR_NO_CODE: 422,
    ERROR_NO_PROFILE: 401,
    ERROR_STATE_MISMATCH: 400,
    ERROR_FXA_ERROR: 400,
}


def safe_redirect(request, url, action):
    if not is_safe_url(url, request):
        url = reverse('home')
    log.info(f'Redirecting after {action} to: {url}')
    return HttpResponseRedirect(url)


def find_user(identity):
    """Try to find a user for a Mozilla accounts profile. Try fxa_id first, but
    if no account is found that way fall back on email (user hasn't logged in
    since the introduction of FxA).

    If the user email belongs to a banned user, raise an error, they shouldn't
    be able to bypass the ban with another FxA with the same email.

    Ther user returned can be a deleted (not banned) user: they will be
    undeleted by the authenticate view.
    """
    try:
        user = UserProfile.objects.get(fxa_id=identity['uid'])
    except UserProfile.DoesNotExist:
        try:
            # Fall back to email for old accounts that never used FxA before.
            user = UserProfile.objects.get(fxa_id=None, email=identity['email'])
        except UserProfile.DoesNotExist:
            return None

        # It's technically possible to raise MultipleObjectsReturned here, if
        # somehow multiple accounts are sharing the same email while having no
        # FxA id. In practice we used to have an uniqueness constraint on
        # email before FxA was introduced, and even for a long time after, so
        # this shouldn't happen.

    is_task_user = user.id == settings.TASK_USER_ID
    # If we find anyone with that email that has ever been banned, we want to
    # prevent them from logging in no matter what.
    is_banned = UserProfile.objects.filter(
        email=identity['email'], banned__isnull=False
    ).exists()
    if is_banned or is_task_user:
        # If the user was banned raise a 403, it's not the prettiest
        # but should be enough.
        # Alternatively if someone tried to log in as the task user then
        # prevent that because that user "owns" a number of important
        # addons and collections, and it's actions are special cased.
        raise exceptions.PermissionDenied()
    return user


def register_user(identity):
    user = UserProfile.objects.create_user(
        email=identity['email'], fxa_id=identity['uid']
    )
    log.info(f'Created user {user} from FxA')
    statsd.incr('accounts.account_created_from_fxa')
    return user


def reregister_user(user):
    user.update(deleted=False)
    log.info(f'Re-created deleted user {user} from FxA')
    statsd.incr('accounts.account_created_from_fxa')
    statsd.incr('accounts.account_recreated_from_fxa')


def update_user(user, identity):
    """Update a user's info from FxA if needed, as well as generating the id
    that is used as part of the session/api token generation."""
    if user.fxa_id != identity['uid'] or user.email != identity['email']:
        log.info(
            'Updating user info from FxA for {pk}. Old {old_email} {old_uid} '
            'New {new_email} {new_uid}'.format(
                pk=user.pk,
                old_email=user.email,
                old_uid=user.fxa_id,
                new_email=identity['email'],
                new_uid=identity['uid'],
            )
        )
        user.update(fxa_id=identity['uid'], email=identity['email'])
    if user.auth_id is None:
        # If the user didn't have an auth id (old user account created before
        # we added the field), generate one for them.
        user.update(auth_id=UserProfile._meta.get_field('auth_id').default())


def login_user(sender, request, user, identity, token_data=None):
    update_user(user, identity)
    log.info('Logging in user %s from FxA', user)
    login(request, user)
    request.session['has_two_factor_authentication'] = identity.get(
        'twoFactorAuthentication'
    )
    if token_data:
        request.session['fxa_access_token_expiry'] = token_data['access_token_expiry']
        request.session['fxa_refresh_token'] = token_data['refresh_token']
        request.session['fxa_config_name'] = token_data['config_name']


def fxa_error_message(message, login_help_url):
    return format_html(
        '{error} <a href="{url}">{help_text}</a>',
        url=login_help_url,
        help_text=_('Need help?'),
        error=message,
    )


LOGIN_HELP_URL = 'https://support.mozilla.org/kb/access-your-add-ons-firefox-accounts'


def parse_next_path(state_parts, request=None):
    next_path = None
    if len(state_parts) == 2:
        # The = signs will be stripped off so we need to add them back
        # but it only cares if there are too few so add 4 of them.
        encoded_path = state_parts[1] + '===='
        try:
            next_path = base64.urlsafe_b64decode(force_bytes(encoded_path)).decode(
                'utf-8'
            )
        except (TypeError, ValueError):
            log.info(f'Error decoding next_path {encoded_path}')
            pass
    if not is_safe_url(next_path, request):
        next_path = None
    return next_path


def with_user(f):
    @functools.wraps(f)
    @use_primary_db
    def inner(self, request):
        # If we get an error, we want a new session without the 2FA enforcement
        # requirement active and with a fresh state for future authentication
        # attempts, so pop them.
        enforce_2fa_for_this_session = request.session.pop('enforce_2fa', False)
        fxa_state_session = request.session.pop('fxa_state', None)

        fxa_config = get_fxa_config(request)
        if request.method == 'GET':
            data = request.query_params
        else:
            data = request.data
        state_parts = data.get('state', '').split(':', 1)
        state = state_parts[0]
        next_path = parse_next_path(state_parts, request)

        if not fxa_state_session or fxa_state_session != state:
            log.info(
                'FxA Auth State mismatch: {state} Session: {fxa_state_session}'.format(
                    state=data.get('state'),
                    fxa_state_session=fxa_state_session,
                )
            )
            # Redirect to / as the state mismatch indicates the next path might
            # not be reliable.
            return safe_redirect(request, '/', ERROR_STATE_MISMATCH)
        elif data.get('error'):
            if enforce_2fa_for_this_session:
                # If we're trying to enforce 2FA, we should try again without
                # prompt=none (and a new state), maybe there is a mismatch
                # between what user we currently have logged in and what
                # Mozilla account the browser is logged into.
                return redirect_for_login_with_2fa_enforced(
                    request,
                    config=fxa_config,
                    next_path=next_path,
                )
            else:
                return safe_redirect(request, next_path, ERROR_FXA_ERROR)
        elif not data.get('code'):
            log.info('No code provided.')
            return safe_redirect(request, next_path, ERROR_NO_CODE)
        elif request.user.is_authenticated and not enforce_2fa_for_this_session:
            return safe_redirect(request, next_path, ERROR_AUTHENTICATED)
        try:
            if use_fake_fxa(fxa_config) and 'fake_fxa_email' in data:
                # Bypassing real authentication, we take the email provided
                # and generate a random fxa id.
                identity = {
                    'email': data['fake_fxa_email'],
                    'uid': 'fake_fxa_id-%s'
                    % force_str(binascii.b2a_hex(os.urandom(16))),
                    'twoFactorAuthentication': data.get(
                        'fake_two_factor_authentication'
                    ),
                }
                id_token, token_data = identity['email'], {}
            else:
                identity, token_data = verify.fxa_identify(
                    data['code'], config=fxa_config
                )
                token_data['config_name'] = get_fxa_config_name(request)
                id_token = token_data.get('id_token')
        except verify.IdentificationError:
            log.info('Profile not found. Code: {}'.format(data['code']))
            return safe_redirect(request, next_path, ERROR_NO_PROFILE)
        else:
            # The following log statement is used by foxsec-pipeline.
            log.info(
                'Logging in FxA user %s',
                identity['email'],
                extra={'sensitive': True},
            )
            user = find_user(identity)
            if (
                user
                and not identity.get('twoFactorAuthentication')
                and (
                    user.is_addon_developer
                    or user.groups_list
                    or enforce_2fa_for_this_session
                )
            ):
                # https://github.com/mozilla/addons/issues/732
                # https://github.com/mozilla/addons-server/issues/20943
                # The user is an add-on developer (with other types of add-ons
                # than just themes) or part of any group (so they are special
                # in some way, may be an admin or a reviewer), or trying to
                # access a page restricted to users with 2FA and they have
                # successfully logged in from FxA, but without a second factor.
                # Immediately redirect them to start the FxA flow again, this
                # time requesting 2FA to be present:
                # They should be automatically logged in FxA with the existing
                # id_token, and should be prompted to create the second factor
                # before coming back to AMO.
                log.info('Redirecting user %s to enforce 2FA', user)
                # There wasn't any error, we can keep the original state.
                request.session['fxa_state'] = fxa_state_session
                return redirect_for_login_with_2fa_enforced(
                    request,
                    next_path=next_path,
                    id_token_hint=id_token,
                )
            return f(
                self,
                request,
                user=user,
                identity=identity,
                next_path=next_path,
                token_data=token_data,
            )

    return inner


class LoginStartView(APIView):
    @method_decorator(never_cache)
    def get(self, request):
        return redirect_for_login(request, next_path=request.GET.get('to', ''))


class AuthenticateView(APIView):
    authentication_classes = (SessionAuthentication,)

    @method_decorator(never_cache)
    @with_user
    def get(self, request, user, identity, next_path, token_data):
        # At this point @with_user guarantees that we have a valid fxa
        # identity. We are proceeding with either registering the user or
        # logging them on.
        if user is None or user.deleted:
            action = 'register'
            if user is None:
                user = register_user(identity)
            else:
                reregister_user(user)
            if not is_safe_url(next_path, request):
                next_path = None
            # If we just reverse() directly, we'd use a prefixer instance
            # initialized from the current view, which would not contain the
            # app information since it's a generic callback, the same for
            # everyone. To ensure the user stays on the app/locale they were
            # on, we extract that information from the next_path if present
            # and set locale/app on the prefixer instance that reverse() will
            # use automatically.
            if next_path:
                if prefixer := get_url_prefix():
                    splitted = prefixer.split_path(next_path)
                    prefixer.locale = splitted[0]
                    prefixer.app = splitted[1]
            edit_page = reverse('users.edit')
            if next_path:
                next_path = f'{edit_page}?to={quote_plus(next_path)}'
            else:
                next_path = edit_page
        else:
            action = 'login'

        login_user(self.__class__, request, user, identity, token_data)
        return safe_redirect(request, next_path, action)


def logout_user(request, response):
    if request.user and request.user.is_authenticated:
        # Logging out invalidates *all* user sessions. A new auth_id will be
        # generated during the next login.
        request.user.update(auth_id=None)
    logout(request)


# This view is not covered by the CORS middleware, see:
# https://github.com/mozilla/addons-server/issues/11100
class SessionView(APIView):
    permission_classes = [
        ByHttpMethod(
            {
                'options': AllowAny,  # Needed for CORS.
                'delete': IsAuthenticated,
            }
        ),
    ]

    def options(self, request, *args, **kwargs):
        response = Response()
        response['Content-Length'] = '0'
        origin = request.META.get('HTTP_ORIGIN')
        if not origin:
            return response
        response[ACCESS_CONTROL_ALLOW_ORIGIN] = origin
        response[ACCESS_CONTROL_ALLOW_CREDENTIALS] = 'true'
        # Mimics the django-cors-headers middleware.
        response[ACCESS_CONTROL_ALLOW_HEADERS] = ', '.join(
            corsheaders_conf.CORS_ALLOW_HEADERS
        )
        response[ACCESS_CONTROL_ALLOW_METHODS] = ', '.join(
            corsheaders_conf.CORS_ALLOW_METHODS
        )
        if corsheaders_conf.CORS_PREFLIGHT_MAX_AGE:
            response[ACCESS_CONTROL_MAX_AGE] = corsheaders_conf.CORS_PREFLIGHT_MAX_AGE
        return response

    def delete(self, request, *args, **kwargs):
        response = Response({'ok': True})
        logout_user(request, response)
        origin = request.META.get('HTTP_ORIGIN')
        if not origin:
            return response
        response[ACCESS_CONTROL_ALLOW_ORIGIN] = origin
        response[ACCESS_CONTROL_ALLOW_CREDENTIALS] = 'true'
        return response


class AllowSelf(BasePermission):
    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        return request.user.is_authenticated and obj == request.user


class AccountViewSet(
    RetrieveModelMixin, UpdateModelMixin, DestroyModelMixin, GenericViewSet
):
    permission_classes = [
        ByHttpMethod(
            {
                'get': AllowAny,
                'head': AllowAny,
                'options': AllowAny,  # Needed for CORS.
                # To edit a profile it has to yours, or be an admin.
                'patch': AnyOf(AllowSelf, GroupPermission(amo.permissions.USERS_EDIT)),
                'delete': AnyOf(AllowSelf, GroupPermission(amo.permissions.USERS_EDIT)),
            }
        ),
    ]
    # Periods are not allowed in username, but we still have some in the
    # database so relax the lookup regexp to allow them to load their profile.
    lookup_value_regex = '[^/]+'

    def get_queryset(self):
        return UserProfile.objects.exclude(deleted=True).all()

    def get_object(self):
        if hasattr(self, 'instance'):
            return self.instance
        identifier = self.kwargs.get('pk')
        self.lookup_field = self.get_lookup_field(identifier)
        self.kwargs[self.lookup_field] = identifier
        self.instance = super().get_object()
        return self.instance

    def get_lookup_field(self, identifier):
        lookup_field = 'pk'
        if identifier and not identifier.isdigit():
            # If the identifier contains anything other than a digit, it's
            # the username.
            lookup_field = 'username'
        return lookup_field

    @property
    def self_view(self):
        return (
            self.request.user.is_authenticated
            and self.get_object() == self.request.user
        )

    @property
    def admin_viewing(self):
        return acl.action_allowed_for(self.request.user, amo.permissions.USERS_EDIT)

    def get_serializer_class(self):
        if self.self_view or self.admin_viewing:
            return SelfUserProfileSerializer
        elif self.get_object().has_full_profile:
            return FullUserProfileSerializer
        else:
            return MinimalUserProfileSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        ActivityLog.objects.create(amo.LOG.USER_DELETED, instance)
        self.perform_destroy(instance)
        response = Response(status=HTTP_204_NO_CONTENT)
        if instance == request.user:
            logout_user(request, response)
        return response

    @action(
        detail=True,
        methods=['delete'],
        permission_classes=[
            AnyOf(AllowSelf, GroupPermission(amo.permissions.USERS_EDIT))
        ],
    )
    def picture(self, request, pk=None):
        user = self.get_object()
        user.delete_picture()
        log.info('User (%s) deleted photo' % user)
        return self.retrieve(request)


class ProfileView(APIView):
    authentication_classes = [
        JWTKeyAuthentication,
        SessionIDAuthentication,
    ]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        account_viewset = AccountViewSet(
            request=request,
            permission_classes=self.permission_classes,
            kwargs={'pk': str(self.request.user.pk)},
        )
        account_viewset.format_kwarg = self.format_kwarg
        return account_viewset.retrieve(request)


class AccountSuperCreate(APIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = [
        IsAuthenticated,
        GroupPermission(amo.permissions.ACCOUNTS_SUPER_CREATE),
    ]

    @waffle_switch('super-create-accounts')
    def post(self, request):
        serializer = AccountSuperCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({'errors': serializer.errors}, status=422)

        data = serializer.data

        group = serializer.validated_data.get('group', None)
        user_token = force_str(binascii.b2a_hex(os.urandom(4)))
        username = data.get('username', f'super-created-{user_token}')
        fxa_id = data.get('fxa_id', None)
        email = data.get('email', f'{username}@addons.mozilla.org')

        user = UserProfile.objects.create(
            username=username,
            email=email,
            fxa_id=fxa_id,
            display_name=f'Super Created {user_token}',
            notes='auto-generated from API',
        )
        user.save()

        if group:
            GroupUser.objects.create(user=user, group=group)

        identity = {'email': email, 'uid': fxa_id}
        login_user(self.__class__, request, user, identity)
        request.session.save()

        log.info(
            'API user {api_user} created and logged in a user from '
            'the super-create API: user_id: {user.pk}; '
            'user_name: {user.username}; fxa_id: {user.fxa_id}; '
            'group: {group}'.format(user=user, api_user=request.user, group=group)
        )

        cookie = {
            'name': settings.SESSION_COOKIE_NAME,
            'value': request.session.session_key,
        }
        cookie['encoded'] = '{name}={value}'.format(**cookie)

        return Response(
            {
                'user_id': user.pk,
                'username': user.username,
                'email': user.email,
                'display_name': user.display_name,
                'groups': list((g.pk, g.name, g.rules) for g in user.groups.all()),
                'fxa_id': user.fxa_id,
                'session_cookie': cookie,
            },
            status=201,
        )


class AccountNotificationMixin:
    def get_user(self):
        raise NotImplementedError

    def _get_default_object(self, notification):
        return UserNotification(
            user=self.get_user(),
            notification_id=notification.id,
            enabled=notification.default_checked,
        )

    def get_queryset(self, dev=False):
        user = self.get_user()
        queryset = UserNotification.objects.filter(user=user)

        # Fetch all `UserNotification` instances and then,
        # overwrite their value with the data from basket.

        # Put it into a dict so we can easily check for existence.
        set_notifications = {
            user_nfn.notification.short: user_nfn
            for user_nfn in queryset
            if user_nfn.notification
        }
        out = []

        newsletters = None  # Lazy - fetch the first time needed.
        by_basket_id = REMOTE_NOTIFICATIONS_BY_BASKET_ID
        for basket_id, notification in by_basket_id.items():
            if notification.group == 'dev' and not user.is_developer:
                # We only return dev notifications for developers.
                continue
            if newsletters is None:
                newsletters = fetch_subscribed_newsletters(user)
            user_notification = self._get_default_object(notification)
            user_notification.enabled = basket_id in newsletters
            set_notifications[notification.short] = user_notification

        include_dev = dev or user.is_developer
        for notification in NOTIFICATIONS_COMBINED:
            if notification.group == 'dev' and not include_dev:
                # We only return dev notifications for developers.
                continue
            out.append(
                set_notifications.get(
                    notification.short,  # It's been set by the user.
                    self._get_default_object(notification),
                )
            )  # Or, default.
        return out


class AccountNotificationViewSet(
    AccountNotificationMixin, ListModelMixin, GenericViewSet
):
    """Returns account notifications.

    If not already set by the user, defaults will be returned.
    """

    permission_classes = [IsAuthenticated]
    # We're pushing the primary permission checking to AccountViewSet for ease.
    account_permission_classes = [
        AnyOf(AllowSelf, GroupPermission(amo.permissions.USERS_EDIT))
    ]
    serializer_class = UserNotificationSerializer
    paginator = None

    def get_user(self):
        return self.get_account_viewset().get_object()

    def get_account_viewset(self):
        if not hasattr(self, 'account_viewset'):
            self.account_viewset = AccountViewSet(
                request=self.request,
                permission_classes=self.account_permission_classes,
                kwargs={'pk': self.kwargs['user_pk']},
            )
        return self.account_viewset

    def create(self, request, *args, **kwargs):
        # Loop through possible notifications.
        queryset = self.get_queryset()
        for notification in queryset:
            # Careful with ifs.  `enabled` will be None|True|False.
            enabled = request.data.get(notification.notification.short)
            if enabled is not None:
                serializer = self.get_serializer(
                    notification, partial=True, data={'enabled': enabled}
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()
        return Response(self.get_serializer(queryset, many=True).data)


class AccountNotificationUnsubscribeView(AccountNotificationMixin, GenericAPIView):
    authentication_classes = (UnsubscribeTokenAuthentication,)
    permission_classes = ()
    serializer_class = UserNotificationSerializer

    def get_user(self):
        return self.request.user

    def post(self, request):
        notification_name = request.data.get('notification')
        serializer = None
        for notification in self.get_queryset(dev=True):
            if notification_name == notification.notification.short:
                serializer = self.get_serializer(
                    notification, partial=True, data={'enabled': False}
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()

        if not serializer:
            raise serializers.ValidationError(
                _('Notification [%s] does not exist') % notification_name
            )
        return Response(serializer.data)


class FxaNotificationView(APIView):
    authentication_classes = []
    permission_classes = []

    FXA_PROFILE_CHANGE_EVENT = (
        'https://schemas.accounts.firefox.com/event/profile-change'
    )
    FXA_DELETE_EVENT = 'https://schemas.accounts.firefox.com/event/delete-user'
    FXA_PASSWORDCHANGE_EVENT = (
        'https://schemas.accounts.firefox.com/event/password-change'
    )

    @classmethod
    def get_fxa_verifying_keys(cls):
        if not hasattr(cls, 'fxa_verifying_keys'):
            response = requests.get(f'{settings.FXA_OAUTH_HOST}/jwks')
            cls.fxa_verifying_keys = (
                response.json().get('keys') if response.status_code == 200 else []
            )

        if not cls.fxa_verifying_keys:
            log.error(
                'FxA webhook: verifying keys are not available (response was %s).',
                response.status_code,
            )
            raise exceptions.AuthenticationFailed(
                'FxA verifying keys are not available.'
            )

        return cls.fxa_verifying_keys

    def get_jwt_payload(self, request):
        client_id = get_fxa_config(request)['client_id']
        authenticated_jwt = None

        auth_header_split = request.headers.get('Authorization', '').split('Bearer ')
        if len(auth_header_split) == 2 and auth_header_split[1]:
            for verifying_key in self.get_fxa_verifying_keys():
                if verifying_key.get('alg') != 'RS256':
                    # we only support RS256
                    continue
                request_jwt = auth_header_split[1]
                try:
                    algorithm = jwt.algorithms.RSAAlgorithm.from_jwk(verifying_key)
                    authenticated_jwt = jwt.decode(
                        request_jwt,
                        algorithm,
                        audience=client_id,
                        leeway=1,
                        algorithms=[verifying_key['alg']],
                    )
                except (ValueError, TypeError, jwt.exceptions.PyJWTError) as e:
                    # We raise when `not authenticated_jwt` below, but log the
                    # error anyway
                    log.exception('FxA webhook: uncaught exception', exc_info=e)
                break

        if not authenticated_jwt:
            raise exceptions.AuthenticationFailed(
                'Could not authenticate JWT with FxA key.'
            )

        return authenticated_jwt

    def process_event(self, uid, event_key, event_data):
        timestamp = (
            change_time / 1000
            if (change_time := event_data.get('changeTime'))
            else time.time()
        )
        if event_key == self.FXA_PROFILE_CHANGE_EVENT:
            log.info(f'Fxa Webhook: Got profile change event for {uid}')
            new_email = event_data.get('email')
            if not new_email:
                log.info(
                    'Email property missing/empty for "%s" event; ignoring' % event_key
                )
            else:
                primary_email_change_event.delay(uid, timestamp, new_email)
        elif event_key == self.FXA_DELETE_EVENT:
            log.info(f'Fxa Webhook: Got delete event for {uid}')
            delete_user_event.delay(uid, timestamp)
        elif event_key == self.FXA_PASSWORDCHANGE_EVENT:
            log.info(f'Fxa Webhook: Got password-change event for {uid}')
            clear_sessions_event.delay(uid, timestamp, 'password-change')
        else:
            log.info('Fxa Webhook: Ignoring unknown event type %r', event_key)

    def post(self, request):
        payload = self.get_jwt_payload(request)
        events = payload.get('events', {})
        uid = payload.get('sub')
        for event_key, event_data in events.items():
            self.process_event(uid, event_key, event_data)

        return Response('202 Accepted', status=202)
