import hashlib
import hmac
import uuid
from functools import partial

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.core.validators import ValidationError

import commonware.log
from django_statsd.clients import statsd
from rest_framework import serializers
from tastypie import http
from tastypie.authorization import Authorization
from tastypie.bundle import Bundle
from tastypie.validation import CleanedDataFormValidation

from access import acl
from mkt.api.authentication import (OAuthAuthentication,
                                    SharedSecretAuthentication)
from mkt.api.authorization import OwnerAuthorization
from mkt.api.base import (CompatRelatedField, CORSResource,
                          http_error, MarketplaceModelResource,
                          MarketplaceResource)
from mkt.api.resources import AppResource
from mkt.constants.apps import INSTALL_TYPE_USER
from mkt.webapps.models import Webapp
from users.models import UserProfile
from users.views import browserid_authenticate

from .forms import LoginForm

log = commonware.log.getLogger('z.account')


class UserSerializer(serializers.ModelSerializer):
    """
    A wacky serializer type that unserializes PK numbers and
    serializes user fields.
    """
    resource_uri = CompatRelatedField(
        view_name='api_dispatch_detail', read_only=True,
        tastypie={'resource_name': 'settings',
                  'api_name': 'account'},
        source='*')
    class Meta:
        model = UserProfile
        fields = ('display_name', 'resource_uri')

    def field_from_native(self, data, files, field_name, into):
        try:
            value = data[field_name]
        except KeyError:
            if self.required:
                raise ValidationError(self.error_messages['required'])
            return
        if value in (None, ''):
            obj = None
        else:
            try:
                obj = UserProfile.objects.get(pk=value)
            except UserProfile.DoesNotExist:
                msg = "Invalid pk '%s' - object does not exist." % (data,)
                raise ValidationError(msg)
        into[self.source or field_name] = obj


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
