import json

import commonware
from curling.lib import HttpClientError, HttpServerError
from tastypie import validation, http
from tastypie.authorization import Authorization
from tastypie.exceptions import ImmediateHttpResponse
from tower import ugettext as _

from mkt.api.authentication import OAuthAuthentication
from mkt.api.base import MarketplaceModelResource
from mkt.developers.forms_payments import BangoPaymentAccountForm
from mkt.developers.models import PaymentAccount

log = commonware.log.getLogger('z.devhub')


class AccountResource(MarketplaceModelResource):
    class Meta(MarketplaceModelResource.Meta):
        validation = validation.FormValidation(
            form_class=BangoPaymentAccountForm)
        queryset = PaymentAccount.objects.all()
        list_allowed_methods = ['get', 'post']
        detail_allowed_methods = ['get', 'post', 'put']
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
        return self.full_hydrate(bundle)
