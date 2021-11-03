import base64
import binascii
import functools
import os
from datetime import datetime
from urllib.parse import quote_plus

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.signals import user_logged_in
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache

import waffle

from corsheaders.conf import conf as corsheaders_conf
from corsheaders.middleware import (
    ACCESS_CONTROL_ALLOW_ORIGIN,
    ACCESS_CONTROL_ALLOW_CREDENTIALS,
    ACCESS_CONTROL_ALLOW_HEADERS,
    ACCESS_CONTROL_ALLOW_METHODS,
    ACCESS_CONTROL_MAX_AGE,
)
from django_statsd.clients import statsd
from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
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
from olympia.amo.decorators import use_primary_db
from olympia.amo.reverse import get_url_prefix
from olympia.amo.utils import fetch_subscribed_newsletters, is_safe_url, use_fake_fxa
from olympia.api.authentication import (
    JWTKeyAuthentication,
    UnsubscribeTokenAuthentication,
    WebTokenAuthentication,
)
from olympia.api.permissions import AnyOf, ByHttpMethod, GroupPermission
from olympia.users.models import UserNotification, UserProfile, FxaToken
from olympia.users.notifications import (
    NOTIFICATIONS_COMBINED,
    REMOTE_NOTIFICATIONS_BY_BASKET_ID,
)

from . import verify
from .serializers import (
    AccountSuperCreateSerializer,
    PublicUserProfileSerializer,
    UserNotificationSerializer,
    UserProfileSerializer,
)
from .utils import (
    add_api_token_to_response,
    fxa_login_url,
    generate_api_token,
    generate_fxa_state,
    API_TOKEN_COOKIE,
)


log = olympia.core.logger.getLogger('accounts')

ERROR_AUTHENTICATED = 'authenticated'
ERROR_NO_CODE = 'no-code'
ERROR_NO_PROFILE = 'no-profile'
ERROR_NO_USER = 'no-user'
ERROR_STATE_MISMATCH = 'state-mismatch'
ERROR_STATUSES = {
    ERROR_AUTHENTICATED: 400,
    ERROR_NO_CODE: 422,
    ERROR_NO_PROFILE: 401,
    ERROR_STATE_MISMATCH: 400,
}
LOGIN_ERROR_MESSAGES = {
    ERROR_AUTHENTICATED: _('You are already logged in.'),
    ERROR_NO_CODE: _('Your login attempt could not be parsed. Please try again.'),
    ERROR_NO_PROFILE: _('Your Firefox Account could not be found. Please try again.'),
    ERROR_STATE_MISMATCH: _('You could not be logged in. Please try again.'),
}


def safe_redirect(request, url, action):
    if not is_safe_url(url, request):
        url = reverse('home')
    log.info(f'Redirecting after {action} to: {url}')
    return HttpResponseRedirect(url)


def find_user(identity):
    """Try to find a user for a Firefox Accounts profile. If the account
    hasn't been migrated we'll need to do the lookup by email but we should
    use the ID after that so check both.

    If we get multiple users we're in some weird state where the accounts need
    to be merged but that behaviour hasn't been defined so let it raise.

    If the user is deleted but we were still able to find them using their
    email or fxa_id, throw an error - they are banned, they shouldn't be able
    to log in anymore.
    """
    try:
        user = UserProfile.objects.get(
            Q(fxa_id=identity['uid']) | Q(email=identity['email'])
        )
        is_task_user = user.id == settings.TASK_USER_ID
        if user.banned or is_task_user:
            # If the user was banned raise a 403, it's not the prettiest
            # but should be enough.
            # Alternatively if someone tried to log in as the task user then
            # prevent that because that user "owns" a number of important
            # addons and collections, and it's actions are special cased.
            raise PermissionDenied()
        return user
    except UserProfile.DoesNotExist:
        return None
    except UserProfile.MultipleObjectsReturned:
        # This shouldn't happen, so let it raise.
        log.error(
            'Found multiple users for %s and %s', identity['email'], identity['uid']
        )
        raise


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
    log.info(f'Logging in user {user} from FxA')
    user_logged_in.send(sender=sender, request=request, user=user)
    login(request, user)
    if token_data:
        fxa_token_object = FxaToken.objects.create(
            user=user,
            access_token_expiry=datetime.fromtimestamp(
                token_data.get('access_token_expiry')
            ),
            refresh_token=token_data.get('refresh_token'),
            config_name=token_data['config_name'],
        )
        request.session['user_token_pk'] = fxa_token_object.pk
        request.session['access_token_expiry'] = token_data.get('access_token_expiry')
        return fxa_token_object


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
        fxa_config = self.get_fxa_config(request)
        if request.method == 'GET':
            data = request.query_params
        else:
            data = request.data

        state_parts = data.get('state', '').split(':', 1)
        state = state_parts[0]
        next_path = parse_next_path(state_parts, request)
        if not data.get('code'):
            log.info('No code provided.')
            return safe_redirect(request, next_path, ERROR_NO_CODE)
        elif (
            not request.session.get('fxa_state')
            or request.session['fxa_state'] != state
        ):
            log.info(
                'State mismatch. URL: {url} Session: {session}'.format(
                    url=data.get('state'),
                    session=request.session.get('fxa_state'),
                )
            )
            return safe_redirect(request, next_path, ERROR_STATE_MISMATCH)
        elif request.user.is_authenticated:
            response = safe_redirect(request, next_path, ERROR_AUTHENTICATED)
            # If the api token cookie is missing but we're still
            # authenticated using the session, add it back.
            if API_TOKEN_COOKIE not in request.COOKIES:
                log.info(
                    'User %s was already authenticated but did not '
                    'have an API token cookie, adding one.',
                    request.user.pk,
                )
                token = generate_api_token(
                    request.user,
                    user_token_pk=request.session.get('user_token_pk'),
                    access_token_expiry=request.session.get('access_token_expiry'),
                )
                response = add_api_token_to_response(response, token)
            return response

        try:
            if use_fake_fxa() and 'fake_fxa_email' in data:
                # Bypassing real authentication, we take the email provided
                # and generate a random fxa id.
                identity = {
                    'email': data['fake_fxa_email'],
                    'uid': 'fake_fxa_id-%s'
                    % force_str(binascii.b2a_hex(os.urandom(16))),
                }
                id_token = identity['email']
                token_data = {}
            else:
                identity, token_data = verify.fxa_identify(
                    data['code'], config=fxa_config
                )
                token_data['config_name'] = self.get_config_name(request)
                id_token = token_data.get('id_token')
        except verify.IdentificationError:
            log.info('Profile not found. Code: {}'.format(data['code']))
            return safe_redirect(request, next_path, ERROR_NO_PROFILE)
        else:
            # The following log statement is used by foxsec-pipeline.
            log.info('Logging in FxA user %s', identity['email'])
            user = find_user(identity)
            # We can't use waffle.flag_is_active() wrapper, because
            # request.user isn't populated at this point (and we don't want
            # it to be).
            flag = waffle.get_waffle_flag_model().get(
                '2fa-enforcement-for-developers-and-special-users'
            )
            enforce_2fa_for_developers_and_special_users = flag.is_active(request) or (
                flag.pk and flag.is_active_for_user(user)
            )
            if (
                user
                and not identity.get('twoFactorAuthentication')
                and enforce_2fa_for_developers_and_special_users
                and (user.is_addon_developer or user.groups_list)
            ):
                # https://github.com/mozilla/addons/issues/732
                # The user is an add-on developer (with other types of
                # add-ons than just themes) or part of any group (so they
                # are special in some way, may be an admin or a reviewer),
                # but hasn't logged in with a second factor. Immediately
                # redirect them to start the FxA flow again, this time
                # requesting 2FA to be present - they should be
                # automatically logged in FxA with the existing token, and
                # should be prompted to create the second factor before
                # coming back to AMO.
                log.info('Redirecting user %s to enforce 2FA', user)
                return HttpResponseRedirect(
                    fxa_login_url(
                        config=fxa_config,
                        state=request.session['fxa_state'],
                        next_path=next_path,
                        action='signin',
                        force_two_factor=True,
                        request=request,
                        id_token=id_token,
                    )
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


class FxAConfigMixin:
    DEFAULT_FXA_CONFIG_NAME = settings.DEFAULT_FXA_CONFIG_NAME
    ALLOWED_FXA_CONFIGS = settings.ALLOWED_FXA_CONFIGS

    def get_config_name(self, request):
        config_name = request.GET.get('config', self.DEFAULT_FXA_CONFIG_NAME)
        if config_name not in self.ALLOWED_FXA_CONFIGS:
            log.info(f'Using default FxA config instead of {config_name}')
            config_name = self.DEFAULT_FXA_CONFIG_NAME
        return config_name

    def get_fxa_config(self, request):
        return settings.FXA_CONFIG[self.get_config_name(request)]


class LoginStartView(FxAConfigMixin, APIView):
    @never_cache
    def get(self, request):
        request.session.setdefault('fxa_state', generate_fxa_state())
        return HttpResponseRedirect(
            fxa_login_url(
                config=self.get_fxa_config(request),
                state=request.session['fxa_state'],
                next_path=request.GET.get('to'),
                action=request.GET.get('action', 'signin'),
                request=request,
            )
        )


class AuthenticateView(FxAConfigMixin, APIView):

    authentication_classes = (SessionAuthentication,)

    @never_cache
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

        fxa_token_object = login_user(
            self.__class__, request, user, identity, token_data
        )
        response = safe_redirect(request, next_path, action)
        if fxa_token_object:
            token = generate_api_token(
                user,
                user_token_pk=fxa_token_object.pk,
                access_token_expiry=fxa_token_object.access_token_expiry.timestamp(),
            )
        else:
            token = generate_api_token(user)
        add_api_token_to_response(response, token)
        return response


def logout_user(request, response):
    if request.user and request.user.is_authenticated:
        # Logging out invalidates *all* user sessions. A new auth_id will be
        # generated during the next login.
        request.user.update(auth_id=None)
    logout(request)
    response.delete_cookie(
        API_TOKEN_COOKIE,
        domain=settings.SESSION_COOKIE_DOMAIN,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )


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
        # action won't exist for other classes that are using this ViewSet.
        can_view_instance = (
            not getattr(self, 'action', None)
            or self.self_view
            or self.admin_viewing
            or self.instance.is_public
        )
        if can_view_instance:
            return self.instance
        else:
            raise Http404

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
        return acl.action_allowed_user(self.request.user, amo.permissions.USERS_EDIT)

    def get_serializer_class(self):
        if self.self_view or self.admin_viewing:
            return UserProfileSerializer
        else:
            return PublicUserProfileSerializer

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
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
    authentication_classes = [JWTKeyAuthentication, WebTokenAuthentication]
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
