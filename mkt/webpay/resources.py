import calendar
import time

from django.conf import settings
from django.conf.urls.defaults import url
from django.core.exceptions import ObjectDoesNotExist

import commonware.log
import django_filters
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from tastypie import fields, http
from tastypie.exceptions import ImmediateHttpResponse
from tastypie.validation import CleanedDataFormValidation

import amo
from amo.helpers import absolutify, urlparams
from amo.urlresolvers import reverse
from amo.utils import send_mail_jinja
from market.models import Price
from stats.models import Contribution

from mkt.api.authentication import (OAuthAuthentication,
                                    OptionalOAuthAuthentication,
                                    RestAnonymousAuthentication,
                                    RestOAuthAuthentication,
                                    RestSharedSecretAuthentication,
                                    SharedSecretAuthentication)
from mkt.api.authorization import (AnonymousReadOnlyAuthorization,
                                   GroupPermission,
                                   OwnerAuthorization,
                                   PermissionAuthorization)
from mkt.api.base import (CORSResource, CORSMixin, http_error,
                          MarketplaceModelResource, MarketplaceResource,
                          MarketplaceView)
from mkt.api.exceptions import AlreadyPurchased
from mkt.purchase.webpay import _prepare_pay, sign_webpay_jwt
from mkt.purchase.utils import payments_enabled
from mkt.webpay.forms import FailureForm, PrepareForm, ProductIconForm
from mkt.webpay.models import ProductIcon
from mkt.webpay.serializers import PriceSerializer


from . import tasks

log = commonware.log.getLogger('z.webpay')


class PreparePayView(CORSMixin, MarketplaceView, GenericAPIView):
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication]
    permission_classes = [AllowAny]
    cors_allowed_methods = ['post']

    def post(self, request, *args, **kwargs):
        form = PrepareForm(request.DATA)
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)
        app = form.cleaned_data['app']

        region = getattr(request, 'REGION', None)
        if region and region.id not in app.get_price_region_ids():
            log.info('Region {0} is not in {1}'
                     .format(region.id, app.get_price_region_ids()))
            if payments_enabled(request):
                log.info('Flag not active')
                return Response('Payments are limited and flag not enabled',
                                status=status.HTTP_403_FORBIDDEN)

        try:
            data = _prepare_pay(request._request, app)
        except AlreadyPurchased:
            return Response({'reason': u'Already purchased app.'},
                            status=status.HTTP_409_CONFLICT)

        return Response(data, status=status.HTTP_201_CREATED)


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
            raise http_error(http.HttpForbidden,
                             'You are not an author of that app.')

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


class PriceFilter(django_filters.FilterSet):
    pricePoint = django_filters.CharFilter(name="name")

    class Meta:
        model = Price
        fields = ['pricePoint']


class PricesViewSet(MarketplaceView, CORSMixin, ListModelMixin,
                    RetrieveModelMixin, GenericViewSet):
    queryset = Price.objects.filter(active=True).order_by('price')
    serializer_class = PriceSerializer
    cors_allowed_methods = ['get']
    authentication_classes = [RestAnonymousAuthentication]
    permission_classes = [AllowAny]
    filter_class = PriceFilter


class FailureNotificationView(MarketplaceView, GenericAPIView):
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication]
    permission_classes = [GroupPermission('Transaction', 'NotifyFailure')]
    queryset = Contribution.objects.filter(uuid__isnull=False)

    def patch(self, request, *args, **kwargs):
        form = FailureForm(request.DATA)
        if not form.is_valid():
            return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

        obj = self.get_object()
        data = {
            'transaction_id': obj,
            'transaction_url': absolutify(
                urlparams(reverse('mkt.developers.transactions'),
                          transaction_id=obj.uuid)),
            'url': form.cleaned_data['url'],
            'retries': form.cleaned_data['attempts']}
        owners = obj.addon.authors.values_list('email', flat=True)
        send_mail_jinja('Payment notification failure.',
                        'webpay/failure.txt',
                        data, recipient_list=owners)
        return Response(status=status.HTTP_202_ACCEPTED)


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


@api_view(['POST'])
@permission_classes((AllowAny,))
def sig_check(request):
    """
    Returns a signed JWT to use for signature checking.

    This is for Nagios checks to ensure that Marketplace's
    signed tokens are valid when processed by Webpay.
    """
    issued_at = calendar.timegm(time.gmtime())
    req = {
        'iss': settings.APP_PURCHASE_KEY,
        'typ': settings.SIG_CHECK_TYP,
        'aud': settings.APP_PURCHASE_AUD,
        'iat': issued_at,
        'exp': issued_at + 3600,  # expires in 1 hour
        'request': {}
    }
    return Response({'sig_check_jwt': sign_webpay_jwt(req)},
                    status=201)
