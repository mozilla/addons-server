from tastypie import fields

from amo.helpers import absolutify, urlparams
from amo.urlresolvers import reverse
from amo.utils import send_mail_jinja
from mkt.api.authentication import (PermissionAuthorization,
                                    MarketplaceAuthentication)
from mkt.api.base import CORSResource, MarketplaceResource
from mkt.webpay.forms import FailureForm
from market.models import Price
from stats.models import Contribution


class PriceResource(CORSResource):
    prices = fields.ListField(attribute='prices', readonly=True)

    class Meta:
        queryset = Price.objects.filter(active=True)
        list_allowed_methods = ['get']
        allowed_methods = ['get']
        resource_name = 'prices'
        fields = ['name']

    def dehydrate_prices(self, bundle):
        return bundle.obj.prices(provider=bundle.request.GET
                                                .get('provider', None))


class FailureNotificationResource(MarketplaceResource):

    class Meta:
        queryset = Contribution.objects.filter(uuid__isnull=False)
        allowed_methods = ['patch']
        resource_name = 'failure'
        authentication = MarketplaceAuthentication()
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
