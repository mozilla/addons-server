from django.conf.urls.defaults import url
from django.core.exceptions import ObjectDoesNotExist

import commonware.log
from tastypie import fields, http
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.validation import CleanedDataFormValidation

import amo
from amo.helpers import absolutify, urlparams
from amo.urlresolvers import reverse
from amo.utils import send_mail_jinja
from mkt.api.authentication import (OAuthAuthentication,
                                    OptionalOAuthAuthentication,
                                    SharedSecretAuthentication)
from mkt.api.authorization import (AnonymousReadOnlyAuthorization,
                                   Authorization, OwnerAuthorization,
                                   PermissionAuthorization)
from mkt.api.base import (CORSResource, GenericObject,
                          MarketplaceModelResource, MarketplaceResource)
from mkt.webpay.forms import FailureForm, PrepareForm, ProductIconForm
from mkt.webpay.models import ProductIcon
from mkt.purchase.webpay import _prepare_pay
from market.models import Price
from stats.models import Contribution

from . import tasks

log = commonware.log.getLogger('z.webpay')


class PreparePayResource(CORSResource, MarketplaceResource):
    webpayJWT = fields.CharField(attribute='webpayJWT', readonly=True)
    contribStatusURL = fields.CharField(attribute='contribStatusURL',
                                        readonly=True)

    class Meta(MarketplaceResource.Meta):
        always_return_data = True
        authentication = (SharedSecretAuthentication(), OAuthAuthentication())
        authorization = Authorization()
        detail_allowed_methods = []
        list_allowed_methods = ['post']
        object_class = GenericObject
        resource_name = 'prepare'
        validation = CleanedDataFormValidation(form_class=PrepareForm)

    def obj_create(self, bundle, request, **kwargs):
        bundle.obj = GenericObject(_prepare_pay(request, bundle.data['app']))
        return bundle


class StatusPayResource(CORSResource, MarketplaceModelResource):

    class Meta(MarketplaceModelResource.Meta):
        always_return_data = True
        authentication = (SharedSecretAuthentication(), OAuthAuthentication())
        authorization = OwnerAuthorization()
        detail_allowed_methods = ['get']
        queryset = Contribution.objects.filter(type=amo.CONTRIB_PURCHASE)
        resource_name = 'status'

    def obj_get(self, request=None, **kw):
        try:
            obj = super(StatusPayResource, self).obj_get(request=request, **kw)
        except ObjectDoesNotExist:
            # Anything that's not correct will be raised as a 404 so that it's
            # harder to iterate over contribution values.
            log.info('Contribution not found')
            return None

        if not OwnerAuthorization().is_authorized(request, object=obj):
            raise ImmediateHttpResponse(response=http.HttpForbidden())

        if not obj.addon.has_purchased(request.amo_user):
            log.info('Not in AddonPurchase table')
            return None

        return obj

    def base_urls(self):
        return [
            url(r"^(?P<resource_name>%s)/(?P<uuid>[^/]+)/$" %
                self._meta.resource_name,
                self.wrap_view('dispatch_detail'),
                name='api_dispatch_detail')
        ]

    def full_dehydrate(self, bundle):
        bundle.data = {'status': 'complete' if bundle.obj.id else 'incomplete'}
        return bundle


class PriceResource(CORSResource, MarketplaceModelResource):
    prices = fields.ListField(attribute='prices', readonly=True)
    localized = fields.DictField(attribute='suggested', readonly=True,
                                 blank=True, null=True)
    pricePoint = fields.CharField(attribute='name', readonly=True)
    name = fields.CharField(attribute='tier_name', readonly=True)

    class Meta:
        detail_allowed_methods = ['get']
        filtering = {'pricePoint': 'exact'}
        include_resource_uri = False
        list_allowed_methods = ['get']
        queryset = Price.objects.filter(active=True)
        resource_name = 'prices'

    def _get_prices(self, bundle):
        """
        Both localized and prices need access to this. But we whichever
        one gets accessed first, cache the result on the object so
        we don't have to worry about it.

        This is going to be called once for each for bundle.obj.
        """
        if not getattr(self, '_prices', {}):
            self._prices = {}

        if bundle.obj.pk not in self._prices:
            self._prices[bundle.obj.pk] = bundle.obj.prices(
                provider=bundle.request.GET.get('provider', None))

        return self._prices[bundle.obj.pk]

    def dehydrate_localized(self, bundle):
        region = bundle.request.REGION
        if not region.default_currency:
            return {}

        # TODO: prices is a list of dicts, can we make this faster?
        for price in self._get_prices(bundle):
            if price['currency'] == region.default_currency:
                result = price.copy()
                result.update({
                    'locale': bundle.obj.get_price_locale(
                        currency=price['currency']),
                    'region': region.name,
                })
                return result

        return {}

    def dehydrate_prices(self, bundle):
        return self._get_prices(bundle)


class FailureNotificationResource(MarketplaceModelResource):

    class Meta:
        authentication = OAuthAuthentication()
        authorization = PermissionAuthorization('Transaction', 'NotifyFailure')
        detail_allowed_methods = ['patch']
        queryset = Contribution.objects.filter(uuid__isnull=False)
        resource_name = 'failure'

    def obj_update(self, bundle, **kw):
        form = FailureForm(bundle.data)
        if not form.is_valid():
            raise self.form_errors(form)

        data = {'transaction_id': bundle.obj,
                'transaction_url': absolutify(
                    urlparams(reverse('mkt.developers.transactions'),
                              transaction_id=bundle.obj.uuid)),
                'url': form.cleaned_data['url'],
                'retries': form.cleaned_data['attempts']}
        owners = bundle.obj.addon.authors.values_list('email', flat=True)
        send_mail_jinja('Payment notification failure.',
                        'webpay/failure.txt',
                        data, recipient_list=owners)
        return bundle


class ProductIconResource(CORSResource, MarketplaceModelResource):
    url = fields.CharField(readonly=True)

    class Meta(MarketplaceResource.Meta):
        authentication = OptionalOAuthAuthentication()
        authorization = AnonymousReadOnlyAuthorization(
                authorizer=PermissionAuthorization('ProductIcon', 'Create'))
        detail_allowed_methods = ['get']
        fields = ['ext_url', 'ext_size', 'size']
        filtering = {
            'ext_url': 'exact',
            'ext_size': 'exact',
            'size': 'exact',
        }
        list_allowed_methods = ['get', 'post']
        queryset = ProductIcon.objects.filter()
        resource_name = 'product/icon'
        validation = CleanedDataFormValidation(form_class=ProductIconForm)

    def dehydrate_url(self, bundle):
        return bundle.obj.url()

    def obj_create(self, bundle, request, **kwargs):
        log.info('Resizing product icon %s @ %s to %s for webpay'
                 % (bundle.data['ext_url'], bundle.data['ext_size'],
                    bundle.data['size']))
        tasks.fetch_product_icon.delay(bundle.data['ext_url'],
                                       bundle.data['ext_size'],
                                       bundle.data['size'])
        # Tell the client that deferred processing will create an object.
        raise ImmediateHttpResponse(response=http.HttpAccepted())
