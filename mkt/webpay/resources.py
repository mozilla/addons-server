import commonware.log
from tastypie import fields, http
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.validation import CleanedDataFormValidation

from amo.helpers import absolutify, urlparams
from amo.urlresolvers import reverse
from amo.utils import send_mail_jinja
from mkt.api.authentication import (OptionalOAuthAuthentication,
                                    OAuthAuthentication)
from mkt.api.authorization import (AnonymousReadOnlyAuthorization,
                                   PermissionAuthorization)
from mkt.api.base import (CORSResource, MarketplaceResource,
                          MarketplaceModelResource)
from mkt.webpay.forms import FailureForm, ProductIconForm
from mkt.webpay.models import ProductIcon
from market.models import Price
from stats.models import Contribution

from . import tasks

log = commonware.log.getLogger('z.webpay')


class PriceResource(CORSResource, MarketplaceModelResource):
    prices = fields.ListField(attribute='prices', readonly=True)
    localized = fields.DictField(attribute='suggested', readonly=True,
                                 blank=True, null=True)

    class Meta:
        queryset = Price.objects.filter(active=True)
        list_allowed_methods = ['get']
        detail_allowed_methods = ['get']
        resource_name = 'prices'
        fields = ['name', 'suggested']

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
        queryset = Contribution.objects.filter(uuid__isnull=False)
        allowed_methods = ['patch']
        resource_name = 'failure'
        authentication = OAuthAuthentication()
        authorization = PermissionAuthorization('Transaction', 'NotifyFailure')

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
        queryset = ProductIcon.objects.filter()
        authentication = OptionalOAuthAuthentication()
        authorization = AnonymousReadOnlyAuthorization(
                authorizer=PermissionAuthorization('ProductIcon', 'Create'))
        detail_allowed_methods = ['get']
        list_allowed_methods = ['get', 'post']
        resource_name = 'product/icon'
        fields = ['ext_url', 'ext_size', 'size']
        filtering = {
            'ext_url': 'exact',
            'ext_size': 'exact',
            'size': 'exact',
        }
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
