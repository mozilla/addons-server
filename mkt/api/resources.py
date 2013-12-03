from django.conf import settings
from django.views import debug

import commonware.log
import raven.base
import waffle
from rest_framework import generics
from rest_framework.decorators import permission_classes
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.serializers import (BooleanField, CharField, ChoiceField,
                                        DecimalField, HyperlinkedIdentityField,
                                        HyperlinkedRelatedField,
                                        ModelSerializer)
from rest_framework.viewsets import (GenericViewSet, ModelViewSet,
                                     ReadOnlyModelViewSet)

import amo
from addons.models import Category, Webapp
from amo.utils import memoize
from constants.payments import PAYMENT_METHOD_CHOICES, PROVIDER_CHOICES
from market.models import Price, PriceCurrency

from mkt.api.authentication import RestOAuthAuthentication
from mkt.api.authorization import AllowAppOwner, GroupPermission
from mkt.api.base import (cors_api_view, CORSMixin, MarketplaceView,
                          SlugOrIdMixin)
from mkt.api.serializers import CarrierSerializer, RegionSerializer
from mkt.carriers import CARRIER_MAP, CARRIERS
from mkt.regions import REGIONS_DICT
from mkt.webapps.tasks import _update_manifest


log = commonware.log.getLogger('z.api')


class TestError(Exception):
    pass


class ErrorViewSet(MarketplaceView, GenericViewSet):
    permission_classes = (AllowAny,)

    def list(self, request, *args, **kwargs):
        # All this does is throw an error. This is used for testing
        # the error handling on dev servers.
        # See mkt.api.exceptions for the error handler code.
        raise TestError('This is a test.')


class CategorySerializer(ModelSerializer):
    name = CharField('name')
    resource_uri = HyperlinkedIdentityField(view_name='app-category-detail')

    class Meta:
        model = Category
        fields = ('name', 'id', 'resource_uri', 'slug')
        view_name = 'category'


class CategoryViewSet(ListModelMixin, RetrieveModelMixin, CORSMixin,
                      SlugOrIdMixin, MarketplaceView, GenericViewSet):
    model = Category
    serializer_class = CategorySerializer
    permission_classes = (AllowAny,)
    cors_allowed_methods = ('get',)
    slug_field = 'slug'

    def get_queryset(self):
        qs = Category.objects.filter(type=amo.ADDON_WEBAPP,
                                     weight__gte=0)
        return qs.order_by('-weight')


def waffles(request):
    switches = ['in-app-sandbox', 'allow-refund', 'rocketfuel']
    flags = ['allow-b2g-paid-submission', 'override-region-exclusion']
    res = dict([s, waffle.switch_is_active(s)] for s in switches)
    res.update(dict([f, waffle.flag_is_active(request, f)] for f in flags))
    return res


@memoize(prefix='config-settings')
def get_settings():
    safe = debug.get_safe_settings()
    _settings = ['SITE_URL']
    return dict([k, safe[k]] for k in _settings)


@cors_api_view(['GET'])
@permission_classes([AllowAny])
def site_config(request):
    """
    A resource that is designed to be exposed externally and contains
    settings or waffle flags that might be relevant to the client app.
    """
    return Response({
            # This is the git commit on IT servers.
            'version': getattr(settings, 'BUILD_ID_JS', ''),
            'flags': waffles(request),
            'settings': get_settings(),
        })


class RegionViewSet(CORSMixin, MarketplaceView, ReadOnlyModelViewSet):
    cors_allowed_methods = ['get']
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = RegionSerializer

    def get_queryset(self, *args, **kwargs):
        return REGIONS_DICT.values()

    def get_object(self, *args, **kwargs):
        return REGIONS_DICT.get(self.kwargs['pk'], None)


class CarrierViewSet(RegionViewSet):
    serializer_class = CarrierSerializer

    def get_queryset(self, *args, **kwargs):
        return CARRIERS

    def get_object(self, *args, **kwargs):
        return CARRIER_MAP.get(self.kwargs['pk'], None)


@cors_api_view(['POST'])
@permission_classes([AllowAny])
def error_reporter(request):
    request._request.CORS = ['POST']
    client = raven.base.Client(settings.SENTRY_DSN)
    client.capture('raven.events.Exception', data=request.DATA)
    return Response(status=204)


class RefreshManifestViewSet(GenericViewSet, CORSMixin):
    model = Webapp
    permission_classes = [AllowAppOwner]
    cors_allowed_methods = ('post',)
    slug_lookup = 'app_slug'

    def detail_post(self, request, **kwargs):
        obj = self.get_object()
        self.check_object_permissions(request, obj)
        if obj.is_packaged:
            return Response(
                status=400,
                data={'reason': 'App is a packaged app.'})
        _update_manifest(obj.pk, True, {})
        return Response(status=204)


class EnumeratedField(ChoiceField):

    def from_native(self, value):
        for k, v in self.choices:
            if value == v:
                return k

    def to_native(self, key):
        for k, v in self.choices:
            if key == k:
                return v


class PriceTierSerializer(ModelSerializer):
    resource_uri = HyperlinkedIdentityField(view_name='price-tier-detail')
    active = BooleanField()
    name = CharField()
    method = EnumeratedField(PAYMENT_METHOD_CHOICES)
    price = DecimalField()

    class Meta:
        model = Price
        fields = ['resource_uri', 'active', 'name', 'method', 'price']


class PriceTierViewSet(generics.CreateAPIView,
                       generics.RetrieveUpdateDestroyAPIView,
                       ModelViewSet):
    permission_classes = [GroupPermission('Prices', 'Edit')]
    authentication_classes = [RestOAuthAuthentication]
    serializer_class = PriceTierSerializer
    model = Price


class PriceCurrencySerializer(ModelSerializer):
    resource_uri = HyperlinkedIdentityField(view_name='price-currency-detail')
    tier = HyperlinkedRelatedField(view_name='price-tier-detail')
    currency = CharField()
    carrier = CharField(required=False)
    price = DecimalField()
    provider = EnumeratedField(PROVIDER_CHOICES)
    method = EnumeratedField(PAYMENT_METHOD_CHOICES)

    class Meta:
        model = PriceCurrency
        fields = ['resource_uri', 'tier', 'currency', 'carrier',
                  'price', 'provider', 'method']


class PriceCurrencyViewSet(ModelViewSet):
    permission_classes = [GroupPermission('Prices', 'Edit')]
    authentication_classes = [RestOAuthAuthentication]
    serializer_class = PriceCurrencySerializer
    model = PriceCurrency
    filter_fields = ('tier', 'provider', 'currency', 'price')

    def post_save(self, obj, created):
        log.info('Price %s %s.' % (obj, 'created' if created else 'updated'))

    def destroy(self, request, *args, **kwargs):
        obj = self.get_object()
        obj.delete()
        log.info('Price %s deleted.' % (obj,))
        return Response(status=204)
