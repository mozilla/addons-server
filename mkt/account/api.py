import hashlib
import hmac
import uuid
from functools import partial

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.core.validators import ValidationError, validate_email

import basket
import commonware.log
from django_statsd.clients import statsd
from tastypie import fields, http
from tastypie.authorization import Authorization
from tastypie.bundle import Bundle
from tastypie.throttle import CacheThrottle
from tastypie.validation import CleanedDataFormValidation

from access import acl
from amo.utils import send_mail_jinja
from mkt.api.authentication import (OAuthAuthentication,
                                    OptionalOAuthAuthentication,
                                    SharedSecretAuthentication)
from mkt.api.authorization import OwnerAuthorization
from mkt.api.base import (CORSResource, GenericObject, http_error,
                          MarketplaceModelResource, MarketplaceResource,
                          PotatoCaptchaResource)
from mkt.api.resources import AppResource
from mkt.constants.apps import INSTALL_TYPE_USER
from mkt.webapps.models import Webapp
from users.models import UserProfile
from users.views import browserid_authenticate

from .forms import FeedbackForm, LoginForm

log = commonware.log.getLogger('z.account')


class Mine(object):

    def obj_get(self, request=None, **kwargs):
        if kwargs.get('pk') == 'mine':
            kwargs['pk'] = request.amo_user.pk

        # TODO: put in acl checks for admins to get other users information.
        obj = super(Mine, self).obj_get(request=request, **kwargs)
        if not OwnerAuthorization().is_authorized(request, object=obj):
            raise http_error(http.HttpForbidden,
                             'You do not have access to that account.')
        return obj


class AccountResource(Mine, CORSResource, MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
        authentication = (SharedSecretAuthentication(), OAuthAuthentication())
        authorization = OwnerAuthorization()
        detail_allowed_methods = ['get', 'patch', 'put']
        fields = ['display_name']
        list_allowed_methods = []
        queryset = UserProfile.objects.filter()
        resource_name = 'settings'


class PermissionResource(Mine, CORSResource, MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
        authentication = (SharedSecretAuthentication(), OAuthAuthentication())
        authorization = OwnerAuthorization()
        detail_allowed_methods = ['get']
        list_allowed_methods = []
        fields = ['resource_uri']
        queryset = UserProfile.objects.filter()
        resource_name = 'permissions'

    def dehydrate(self, bundle):
        allowed = partial(acl.action_allowed, bundle.request)
        permissions = {
            'admin': allowed('Admin', '%'),
            'developer': bundle.request.amo_user.is_app_developer,
            'localizer': allowed('Localizers', '%'),
            'lookup': allowed('AccountLookup', '%'),
            'curator': allowed('Collections', 'Curate'),
            'reviewer': acl.action_allowed(bundle.request, 'Apps', 'Review'),
            'webpay': (allowed('Transaction', 'NotifyFailure')
                       and allowed('ProductIcon', 'Create')),
        }
        bundle.data['permissions'] = permissions
        return bundle


class InstalledResource(AppResource):

    class Meta(AppResource.Meta):
        authentication = (SharedSecretAuthentication(), OAuthAuthentication())
        authorization = OwnerAuthorization()
        detail_allowed_methods = []
        list_allowed_methods = ['get']
        resource_name = 'installed/mine'
        slug_lookup = None

    def obj_get_list(self, request=None, **kwargs):
        return Webapp.objects.no_cache().filter(
            installed__user=request.amo_user,
            installed__install_type=INSTALL_TYPE_USER)


class LoginResource(CORSResource, MarketplaceResource):

    class Meta(MarketplaceResource.Meta):
        always_return_data = True
        authorization = Authorization()
        list_allowed_methods = ['post']
        object_class = dict
        resource_name = 'login'
        validation = CleanedDataFormValidation(form_class=LoginForm)

    def get_token(self, email):
        unique_id = uuid.uuid4().hex

        consumer_id = hashlib.sha1(
            email + settings.SECRET_KEY).hexdigest()

        hm = hmac.new(
            unique_id + settings.SECRET_KEY,
            consumer_id, hashlib.sha512)
        return ','.join((email, hm.hexdigest(), unique_id))

    def obj_create(self, bundle, request, **kwargs):
        with statsd.timer('auth.browserid.verify'):
            profile, msg = browserid_authenticate(
                request, bundle.data['assertion'],
                browserid_audience=bundle.data['audience'],
                is_native=bundle.data.get('is_native', False)
            )
        if profile is None:
            log.info('No profile: %s' % (msg or ''))
            raise http_error(http.HttpUnauthorized,
                             'No profile.')

        request.user, request.amo_user = profile.user, profile
        request.groups = profile.groups.all()

        # TODO: move this to the signal.
        profile.log_login_attempt(True)
        user_logged_in.send(sender=profile.user.__class__, request=request,
                            user=profile.user)
        bundle.data = {
            'error': None,
            'token': self.get_token(request.amo_user.email),
            'settings': {
                'display_name': request.amo_user.display_name,
                'email': request.amo_user.email,
            }
        }
        bundle.data.update(PermissionResource()
                           .dehydrate(Bundle(request=request)).data)
        return bundle


class FeedbackResource(PotatoCaptchaResource, CORSResource,
                       MarketplaceResource):
    feedback = fields.CharField(attribute='feedback')
    platform = fields.CharField(attribute='platform', null=True)
    chromeless = fields.CharField(attribute='chromeless', null=True)
    from_url = fields.CharField(attribute='from_url', null=True)
    user = fields.CharField(attribute='user', null=True)
    user_agent = fields.CharField(attribute='user_agent', blank=True)
    ip_address = fields.CharField(attribute='ip_address', blank=True)

    class Meta(MarketplaceResource.Meta):
        resource_name = 'feedback'
        always_return_data = True
        list_allowed_methods = ['post']
        detail_allowed_methods = []
        authentication = OptionalOAuthAuthentication()
        authorization = Authorization()
        object_class = GenericObject
        include_resource_uri = False
        throttle = CacheThrottle(throttle_at=30)

    def _send_email(self, bundle):
        """
        Send feedback email from the valid bundle.
        """
        user = bundle.data.get('user')
        sender = getattr(user, 'email', settings.NOBODY_EMAIL)
        send_mail_jinja(u'Marketplace Feedback', 'account/email/feedback.txt',
                        bundle.data, from_email=sender,
                        recipient_list=[settings.MKT_FEEDBACK_EMAIL])

    def hydrate(self, bundle):
        """
        Add the authenticated user to the bundle.
        """
        if 'platform' not in bundle.data:
            bundle.data['platform'] = bundle.request.GET.get('dev', '')

        bundle.data.update({
            'user': bundle.request.amo_user,
            'user_agent': bundle.request.META.get('HTTP_USER_AGENT', ''),
            'ip_address': bundle.request.META.get('REMOTE_ADDR', '')
        })
        return bundle

    def dehydrate(self, bundle):
        """
        Strip the `user_agent` and `ip_address` fields before presenting to the
        consumer.
        """
        del bundle.data['user_agent']
        del bundle.data['ip_address']
        return bundle

    def get_resource_uri(self, bundle_or_obj=None):
        """
        Noop needed to prevent NotImplementedError.
        """
        return ''

    def obj_create(self, bundle, request=None, **kwargs):
        bundle.obj = self._meta.object_class(**kwargs)
        bundle = self.full_hydrate(bundle)

        form = FeedbackForm(bundle.data, request=request)
        if not form.is_valid():
            raise self.form_errors(form)

        self._send_email(bundle)

        return bundle


class NewsletterResource(CORSResource, MarketplaceResource):
    email = fields.CharField(attribute='email')

    class Meta(MarketplaceResource.Meta):
        list_allowed_methods = ['post']
        detail_allowed_methods = []
        resource_name = 'newsletter'
        authorization = Authorization()
        authentication = (SharedSecretAuthentication(), OAuthAuthentication())

    def post_list(self, request, **kwargs):
        data = self.deserialize(request, request.raw_post_data,
                                format='application/json')
        email = data['email']
        try:
            validate_email(email)
        except ValidationError:
            raise http_error(http.HttpBadRequest, 'Invalid email address')
        basket.subscribe(data['email'], 'marketplace',
                         format='H', country=request.REGION.slug,
                         lang=request.LANG, optin='Y',
                         trigger_welcome='Y')
