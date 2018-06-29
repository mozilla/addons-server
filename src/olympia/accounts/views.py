import base64
import functools
import os

from django.conf import settings
from django.contrib.auth import login, logout
from django.core import signing
from django.db.models import Q
from django.http import Http404, HttpResponseRedirect
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.html import format_html
from django.utils.http import is_safe_url
from django.utils.translation import ugettext, ugettext_lazy as _

import waffle

from rest_framework import serializers
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import detail_route
from rest_framework.mixins import (
    DestroyModelMixin, ListModelMixin, RetrieveModelMixin, UpdateModelMixin)
from rest_framework.permissions import (
    AllowAny, BasePermission, IsAuthenticated)
from rest_framework.response import Response
from rest_framework.status import HTTP_204_NO_CONTENT
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet
from waffle.decorators import waffle_switch

import olympia.core.logger

from olympia import amo
from olympia.access import acl
from olympia.access.models import GroupUser
from olympia.amo import messages
from olympia.amo.decorators import write
from olympia.amo.utils import fetch_subscribed_newsletters
from olympia.api.authentication import (
    JWTKeyAuthentication, WebTokenAuthentication)
from olympia.users import tasks
from olympia.api.permissions import AnyOf, ByHttpMethod, GroupPermission
from olympia.users.models import UserNotification, UserProfile
from olympia.users.notifications import (
    NOTIFICATIONS_COMBINED, REMOTE_NOTIFICATIONS_BY_BASKET_ID)

from . import verify
from .serializers import (
    AccountSuperCreateSerializer, PublicUserProfileSerializer,
    UserNotificationSerializer, UserProfileSerializer)
from .utils import fxa_login_url, generate_fxa_state


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
    ERROR_AUTHENTICATED: _(u'You are already logged in.'),
    ERROR_NO_CODE:
        _(u'Your login attempt could not be parsed. Please try again.'),
    ERROR_NO_PROFILE:
        _(u'Your Firefox Account could not be found. Please try again.'),
    ERROR_STATE_MISMATCH: _(u'You could not be logged in. Please try again.'),
}

# Name of the cookie that contains the auth token for the API. It used to be
# "api_auth_token" but we had to change it because it wasn't set on the right
# domain, and we couldn't clear both the old and new versions at the same time,
# since sending multiple Set-Cookie headers with the same name is not allowed
# by the spec, even if they have a distinct domain attribute.
API_TOKEN_COOKIE = 'frontend_auth_token'


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
    """Update a user's info from FxA if needed, as well as generating the id
    that is used as part of the session/api token generation."""
    if (user.fxa_id != identity['uid'] or
            user.email != identity['email']):
        log.info(
            'Updating user info from FxA for {pk}. Old {old_email} {old_uid} '
            'New {new_email} {new_uid}'.format(
                pk=user.pk, old_email=user.email, old_uid=user.fxa_id,
                new_email=identity['email'], new_uid=identity['uid']))
        user.update(fxa_id=identity['uid'], email=identity['email'])
    if user.auth_id is None:
        # If the user didn't have an auth id (old user account created before
        # we added the field), generate one for them.
        user.update(auth_id=UserProfile._meta.get_field('auth_id').default())


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
        response = Response({'error': error}, status=status)
    else:
        if not is_safe_url(next_path):
            next_path = None
        messages.error(
            request, fxa_error_message(LOGIN_ERROR_MESSAGES[error]),
            extra_tags='fxa')
        if next_path is None:
            response = HttpResponseRedirect(reverse('users.login'))
        else:
            response = HttpResponseRedirect(next_path)
    return response


def parse_next_path(state_parts):
    next_path = None
    if len(state_parts) == 2:
        # The = signs will be stripped off so we need to add them back
        # but it only cares if there are too few so add 4 of them.
        encoded_path = state_parts[1] + '===='
        try:
            next_path = base64.urlsafe_b64decode(
                force_bytes(encoded_path)).decode('utf-8')
        except (TypeError, ValueError):
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
                if hasattr(self, 'get_fxa_config'):
                    fxa_config = self.get_fxa_config(request)
                else:
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
                response = render_error(
                    request, ERROR_AUTHENTICATED, next_path=next_path,
                    format=format)
                # If the api token cookie is missing but we're still
                # authenticated using the session, add it back.
                if API_TOKEN_COOKIE not in request.COOKIES:
                    log.info('User %s was already authenticated but did not '
                             'have an API token cookie, adding one.',
                             request.user.pk)
                    response = add_api_token_to_response(
                        response, request.user)
                return response
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


def generate_api_token(user):
    """Generate a new API token for a given user."""
    data = {
        'auth_hash': user.get_session_auth_hash(),
        'user_id': user.pk,
    }
    return signing.dumps(data, salt=WebTokenAuthentication.salt)


def add_api_token_to_response(response, user):
    """Generate API token and add it to the response (both as a `token` key in
    the response if it was json and by setting a cookie named API_TOKEN_COOKIE.
    """
    token = generate_api_token(user)
    if hasattr(response, 'data'):
        response.data['token'] = token
    # Also include the API token in a session cookie, so that it is
    # available for universal frontend apps.
    response.set_cookie(
        API_TOKEN_COOKIE,
        token,
        domain=settings.SESSION_COOKIE_DOMAIN,
        max_age=settings.SESSION_COOKIE_AGE,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=settings.SESSION_COOKIE_HTTPONLY)

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


class AuthenticateView(FxAConfigMixin, APIView):
    DEFAULT_FXA_CONFIG_NAME = settings.DEFAULT_FXA_CONFIG_NAME
    ALLOWED_FXA_CONFIGS = settings.ALLOWED_FXA_CONFIGS

    authentication_classes = (SessionAuthentication,)

    @with_user(format='html')
    def get(self, request, user, identity, next_path):
        if user is None:
            user = register_user(request, identity)
            fxa_config = self.get_fxa_config(request)
            if fxa_config.get('skip_register_redirect'):
                response = safe_redirect(next_path, 'register')
            else:
                response = safe_redirect(reverse('users.edit'), 'register')
        else:
            login_user(request, user, identity)
            response = safe_redirect(next_path, 'login')
        add_api_token_to_response(response, user)
        return response


def logout_user(request, response):
    logout(request)
    response.delete_cookie(
        API_TOKEN_COOKIE, domain=settings.SESSION_COOKIE_DOMAIN)


class SessionView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        response = Response({'ok': True})
        logout_user(request, response)
        return response


class AllowSelf(BasePermission):
    def has_permission(self, request, view):
        return True

    def has_object_permission(self, request, view, obj):
        return request.user.is_authenticated() and obj == request.user


class AccountViewSet(RetrieveModelMixin, UpdateModelMixin, DestroyModelMixin,
                     GenericViewSet):
    permission_classes = [
        ByHttpMethod({
            'get': AllowAny,
            'head': AllowAny,
            'options': AllowAny,  # Needed for CORS.
            # To edit a profile it has to yours, or be an admin.
            'patch': AnyOf(AllowSelf, GroupPermission(
                amo.permissions.USERS_EDIT)),
            'delete': AnyOf(AllowSelf, GroupPermission(
                amo.permissions.USERS_EDIT)),
        }),
    ]

    def get_queryset(self):
        return UserProfile.objects.all()

    def get_object(self):
        if hasattr(self, 'instance'):
            return self.instance
        identifier = self.kwargs.get('pk')
        self.lookup_field = self.get_lookup_field(identifier)
        self.kwargs[self.lookup_field] = identifier
        self.instance = super(AccountViewSet, self).get_object()
        # action won't exist for other classes that are using this ViewSet.
        can_view_instance = (
            not getattr(self, 'action', None) or
            self.self_view or
            self.admin_viewing or
            self.instance.is_public)
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
            self.request.user.is_authenticated() and
            self.get_object() == self.request.user)

    @property
    def admin_viewing(self):
        return acl.action_allowed_user(
            self.request.user, amo.permissions.USERS_EDIT)

    def get_serializer_class(self):
        if self.self_view or self.admin_viewing:
            return UserProfileSerializer
        else:
            return PublicUserProfileSerializer

    def perform_destroy(self, instance):
        if instance.is_developer:
            raise serializers.ValidationError(ugettext(
                u'Developers of add-ons or themes cannot delete their '
                u'account. You must delete all add-ons and themes linked to '
                u'this account, or transfer them to other users.'))
        return super(AccountViewSet, self).perform_destroy(instance)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        response = Response(status=HTTP_204_NO_CONTENT)
        if instance == request.user:
            logout_user(request, response)
        return response

    @detail_route(
        methods=['delete'], permission_classes=[
            AnyOf(AllowSelf, GroupPermission(amo.permissions.USERS_EDIT))])
    def picture(self, request, pk=None):
        user = self.get_object()
        user.update(picture_type=None)
        log.debug(u'User (%s) deleted photo' % user)
        tasks.delete_photo.delay(user.picture_path)
        return self.retrieve(request)


class ProfileView(APIView):
    authentication_classes = [JWTKeyAuthentication, WebTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        account_viewset = AccountViewSet(
            request=request,
            permission_classes=self.permission_classes,
            kwargs={'pk': unicode(self.request.user.pk)})
        account_viewset.format_kwarg = self.format_kwarg
        return account_viewset.retrieve(request)


class AccountSuperCreate(APIView):
    authentication_classes = [JWTKeyAuthentication]
    permission_classes = [
        IsAuthenticated,
        GroupPermission(amo.permissions.ACCOUNTS_SUPER_CREATE)]

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


class AccountNotificationViewSet(ListModelMixin, GenericViewSet):
    """Returns account notifications.

    If not already set by the user, defaults will be returned.
    """

    permission_classes = [IsAuthenticated]
    # We're pushing the primary permission checking to AccountViewSet for ease.
    account_permission_classes = [
        AnyOf(AllowSelf, GroupPermission(amo.permissions.USERS_EDIT))]
    serializer_class = UserNotificationSerializer
    paginator = None

    def get_account_viewset(self):
        if not hasattr(self, 'account_viewset'):
            self.account_viewset = AccountViewSet(
                request=self.request,
                permission_classes=self.account_permission_classes,
                kwargs={'pk': self.kwargs['user_pk']})
        return self.account_viewset

    def _get_default_object(self, notification):
        return UserNotification(
            user=self.get_account_viewset().get_object(),
            notification_id=notification.id,
            enabled=notification.default_checked)

    def get_queryset(self):
        user = self.get_account_viewset().get_object()
        queryset = UserNotification.objects.filter(user=user)

        # Fetch all `UserNotification` instances and then, if the
        # waffle-switch is active overwrite their value with the
        # data from basket. Once we switched the integration "on" on prod
        # all `UserNotification` instances that are now handled by basket
        # can be deleted.

        # Put it into a dict so we can easily check for existence.
        set_notifications = {
            user_nfn.notification.short: user_nfn for user_nfn in queryset}
        out = []

        if waffle.switch_is_active('activate-basket-sync'):
            newsletters = None  # Lazy - fetch the first time needed.
            by_basket_id = REMOTE_NOTIFICATIONS_BY_BASKET_ID
            for basket_id, notification in by_basket_id.items():
                # If we have this notification in the db queryset, drop it.
                set_notifications.pop(notification.short, None)

                if notification.group == 'dev' and not user.is_developer:
                    # We only return dev notifications for developers.
                    continue
                if newsletters is None:
                    newsletters = fetch_subscribed_newsletters(user)
                notification = self._get_default_object(notification)
                notification.enabled = basket_id in newsletters
                out.append(notification)

        for notification in NOTIFICATIONS_COMBINED:
            if notification.group == 'dev' and not user.is_developer:
                # We only return dev notifications for developers.
                continue
            out.append(set_notifications.get(
                notification.short,  # It's been set by the user.
                self._get_default_object(notification)))  # Or, default.
        return out

    def create(self, request, *args, **kwargs):
        # Loop through possible notifications.
        queryset = self.get_queryset()
        for notification in queryset:
            # Careful with ifs.  Enabled will be None|True|False.
            enabled = request.data.get(notification.notification.short)
            if enabled is not None:
                serializer = self.get_serializer(
                    notification, partial=True, data={'enabled': enabled})
                serializer.is_valid(raise_exception=True)
                serializer.save()
        return Response(self.get_serializer(queryset, many=True).data)
