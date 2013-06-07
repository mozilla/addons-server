import json

import commonware
from curling.lib import HttpClientError, HttpServerError
from tastypie import http
from tastypie.authorization import Authorization
from tastypie.exceptions import ImmediateHttpResponse, NotFound
from tower import ugettext as _

from mkt.api.authentication import OAuthAuthentication
from mkt.api.base import MarketplaceModelResource
from mkt.developers.forms_payments import BangoPaymentAccountForm
from mkt.developers.models import PaymentAccount

log = commonware.log.getLogger('z.devhub')


class BangoFormValidation(object):

    def is_valid(self, bundle, request=None):
        data = bundle.data or {}
        if request.method == 'PUT':
            form = BangoPaymentAccountForm(data, account=True)
        else:
            form = BangoPaymentAccountForm(data)
        if form.is_valid():
            return {}
        return form.errors


class AccountResource(MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
        validation = BangoFormValidation()
        queryset = PaymentAccount.objects.all()
        list_allowed_methods = ['get', 'post']
        detail_allowed_methods = ['get', 'put', 'delete']
        authentication = OAuthAuthentication()
        authorization = Authorization()
        resource_name = 'account'

    def get_object_list(self, request):
        qs = MarketplaceModelResource.get_object_list(self, request)
        return qs.filter(user=request.amo_user, inactive=False)

    def obj_create(self, bundle, request=None, **kwargs):
        try:
            bundle.obj = PaymentAccount.create_bango(
                request.amo_user, bundle.data)
        except HttpClientError as e:
            log.error('Client error create Bango account; %s' % e)
            raise ImmediateHttpResponse(
                http.HttpApplicationError(json.dumps(e.content)))
        except HttpServerError as e:
            log.error('Error creating Bango payment account; %s' % e)
            raise ImmediateHttpResponse(http.HttpApplicationError(
                _(u'Could not connect to payment server.')))
        return bundle

    def obj_update(self, bundle, request=None, **kwargs):
        bundle.obj = self.obj_get(request, **kwargs)
        bundle.obj.update_account_details(**bundle.data)
        return bundle

    def full_dehydrate(self, bundle):
        bundle.data = bundle.obj.get_details()
        bundle.data['resource_uri'] = self.get_resource_uri(bundle)
        return bundle

    def obj_delete(self, request=None, **kwargs):
        try:
            account = self.obj_get(request, **kwargs)
        except PaymentAccount.DoesNotExist:
            raise NotFound('A model instance matching the provided arguments '
                           'could not be found.')
        account.cancel()
        log.info('Account cancelled: %s' % account.pk)
