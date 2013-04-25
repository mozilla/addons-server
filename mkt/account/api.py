import hashlib
import hmac
import uuid

from django.conf import settings

from django_browserid import get_audience
from tastypie import fields, http
from tastypie.authorization import Authorization
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.throttle import CacheThrottle

from amo.utils import send_mail_jinja
from mkt.api.authentication import (OAuthAuthentication,
                                    OptionalOAuthAuthentication,
                                    SharedSecretAuthentication)
from mkt.api.authorization import OwnerAuthorization
from mkt.api.base import (CORSResource, GenericObject,
                          MarketplaceModelResource, MarketplaceResource,
                          PotatoCaptchaResource)
from mkt.api.resources import AppResource
from mkt.constants.apps import INSTALL_TYPE_USER
from mkt.webapps.models import Webapp
from users.models import UserProfile
from users.views import browserid_login

from .forms import FeedbackForm, LoginForm


class AccountResource(CORSResource, MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
        authentication = (SharedSecretAuthentication(), OAuthAuthentication())
        authorization = OwnerAuthorization()
        detail_allowed_methods = ['get', 'patch', 'put']
        fields = ['display_name']
        list_allowed_methods = []
        queryset = UserProfile.objects.filter()
        resource_name = 'settings'

    def obj_get(self, request=None, **kwargs):
        if kwargs.get('pk') == 'mine':
            kwargs['pk'] = request.amo_user.pk

        # TODO: put in acl checks for admins to get other users information.
        obj = super(AccountResource, self).obj_get(request=request, **kwargs)
        if not OwnerAuthorization().is_authorized(request, object=obj):
            raise ImmediateHttpResponse(response=http.HttpForbidden())
        return obj


class InstalledResource(AppResource):

    class Meta(AppResource.Meta):
        authentication = (SharedSecretAuthentication(), OAuthAuthentication())
        authorization = OwnerAuthorization()
        detail_allowed_methods = []
        list_allowed_methods = ['get']
        resource_name = 'installed/mine'
        slug_lookup = None

    def obj_get_list(self, request=None, **kwargs):
        return Webapp.objects.filter(installed__user=request.amo_user,
                                     installed__install_type=INSTALL_TYPE_USER)


class LoginResource(CORSResource, MarketplaceResource):
    class Meta(MarketplaceResource.Meta):
        resource_name = 'login'
        always_return_data = True
        list_allowed_methods = ['post']
        authorization = Authorization()

    def get_token(self, email):
        unique_id = uuid.uuid4().hex

        consumer_id = hashlib.sha1(
            email + settings.SECRET_KEY).hexdigest()

        hm = hmac.new(
            unique_id + settings.SECRET_KEY,
            consumer_id, hashlib.sha512)
        return ','.join((email, hm.hexdigest(), unique_id))

    def post_list(self, request, **kwargs):
        form = LoginForm(request.POST)
        if not form.is_valid():
            raise self.form_errors(form)

        # We use request.POST rather than form.cleaned_data to conform to what
        # django_browserid expects. That means that any mutations performed by
        # LoginForm validation are lost. Be careful!
        if 'audience' in request.POST:
            audience = lambda r: r.POST.get('audience')
        else:
            audience = get_audience

        res = browserid_login(request, browserid_audience=audience)
        if res.status_code == 200:
            return self.create_response(request, {
                'error': None,
                'token': self.get_token(request.user.email),
                'settings': {
                    'display_name': (UserProfile.objects
                                     .get(user=request.user).display_name),
                    'email': request.user.email,
                }
            })
        return res


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
