from functools import partial

from django.core.exceptions import PermissionDenied

from rest_framework.mixins import (CreateModelMixin, DestroyModelMixin,
                                   RetrieveModelMixin, UpdateModelMixin)
from rest_framework.permissions import BasePermission
from rest_framework.relations import HyperlinkedRelatedField
from rest_framework.response import Response
from rest_framework.serializers import (HyperlinkedModelSerializer,
                                        ValidationError)
from rest_framework.viewsets import GenericViewSet

import amo
from addons.models import AddonUpsell

from mkt.api.authorization import (AllowAppOwner, PermissionAuthorization,
                                   switch)
from mkt.api.base import AppViewSet, CompatRelatedField
from mkt.constants.payments import PAYMENT_STATUSES
from mkt.developers.forms_payments import PaymentCheckForm
from mkt.developers.models import AddonPaymentAccount
from mkt.webapps.models import Webapp

from lib.pay_server import get_client


class PaymentSerializer(HyperlinkedModelSerializer):
    upsell = HyperlinkedRelatedField(read_only=True, required=False,
                                     view_name='app-upsell-detail')
    account = HyperlinkedRelatedField(read_only=True, required=False,
                                      source='app_payment_account',
                                      view_name='app-payment-account-detail')

    class Meta:
        model = Webapp
        fields = ('upsell', 'account', 'url')
        view_name = 'app-payments-detail'


class PaymentViewSet(RetrieveModelMixin, GenericViewSet):
    permission_classes = (AllowAppOwner,)
    queryset = Webapp.objects.filter()
    serializer_class = PaymentSerializer


class UpsellSerializer(HyperlinkedModelSerializer):
    free = premium = CompatRelatedField(
        tastypie={'resource_name': 'app', 'api_name': 'apps'},
        view_name='api_dispatch_detail')

    class Meta:
        model = AddonUpsell
        fields = ('free', 'premium', 'created', 'modified', 'url')
        view_name = 'app-upsell-detail'

    def validate(self, attrs):
        if attrs['free'].premium_type not in amo.ADDON_FREES:
            raise ValidationError('Upsell must be from a free app.')

        if attrs['premium'].premium_type in amo.ADDON_FREES:
            raise ValidationError('Upsell must be to a premium app.')

        return attrs


class UpsellPermission(BasePermission):
    """
    Permissions on the upsell object, is determined by permissions on the
    free and premium object.
    """

    def check(self, request, free, premium):
        allow = AllowAppOwner()
        for app in free, premium:
            if app and not allow.has_object_permission(request, '', app):
                return False
        return True

    def has_object_permission(self, request, view, object):
        return self.check(request, object.free, object.premium)


class UpsellViewSet(CreateModelMixin, DestroyModelMixin, RetrieveModelMixin,
                    UpdateModelMixin, GenericViewSet):
    permission_classes = (switch('allow-b2g-paid-submission'),
                          UpsellPermission,)
    queryset = AddonUpsell.objects.filter()
    serializer_class = UpsellSerializer

    def pre_save(self, obj):
        if not UpsellPermission().check(self.request, obj.free, obj.premium):
            raise PermissionDenied('Not allowed to alter that object')


class PaymentAccountPermission(BasePermission):
    """
    Permissions on the payment account object, is determined by permissions on
    the app the account is being used for.
    """

    def check(self, request, app):
        if AllowAppOwner().has_object_permission(request, '', app):
            return True
        return False

    def has_object_permission(self, request, view, object):
        return self.check(request, object.addon)


class PaymentAccountSerializer(HyperlinkedModelSerializer):
    addon = CompatRelatedField(
        source='addon',
        tastypie={'resource_name': 'app', 'api_name': 'apps'},
        view_name='api_dispatch_detail')
    payment_account = CompatRelatedField(
        tastypie={'resource_name': 'account', 'api_name': 'payments'},
        view_name='api_dispatch_detail')

    class Meta:
        model = AddonPaymentAccount
        fields = ('addon', 'payment_account', 'provider',
                  'created', 'modified', 'url')
        view_name = 'app-payment-account-detail'

    def validate(self, attrs):
        if attrs['addon'].premium_type in amo.ADDON_FREES:
            raise ValidationError('App must be a premium app.')

        return attrs


class PaymentAccountViewSet(CreateModelMixin, RetrieveModelMixin,
                            UpdateModelMixin, GenericViewSet):
    permission_classes = (PaymentAccountPermission,)
    queryset = AddonPaymentAccount.objects.filter()
    serializer_class = PaymentAccountSerializer

    def pre_save(self, obj):
        if not PaymentAccountPermission().check(self.request, obj.addon):
            raise PermissionDenied('Not allowed to alter that object.')

        if self.request.method != 'POST':
            addon = obj.__class__.objects.no_cache().get(pk=obj.pk).addon
            if not obj.addon == addon:
                # This should be a 400 error.
                raise PermissionDenied('Cannot change the add-on.')

    def post_save(self, obj, created=False):
        """Ensure that the setup_bango method is called after creation."""
        if created:
            uri = obj.__class__.setup_bango(obj.provider, obj.addon,
                                            obj.payment_account)
            obj.product_uri = uri
            obj.save()


class PaymentCheckViewSet(AppViewSet):
    permission_classes = (AllowAppOwner,)
    form = PaymentCheckForm

    def create(self, request, *args, **kwargs):
        """
        We aren't actually creating objects, but proxying them
        through to solitude.
        """
        if not self.app:
            return Response('', status=400)

        self.check_object_permissions(request, self.app)
        client = get_client()

        res = client.api.bango.status.post(
                data={'seller_product_bango':
                      self.app.app_payment_account.account_uri})

        filtered = {
            'bango': {
                'status': PAYMENT_STATUSES[res['status']],
                'errors': ''
            },
        }
        return Response(filtered, status=200)


class PaymentDebugViewSet(AppViewSet):
    permission_classes = (partial(PermissionAuthorization,
                                  'Transaction', 'Debug',),)
    form = PaymentCheckForm

    def list(self, request, *args, **kwargs):
        if not self.app:
            return Response('', status=400)

        client = get_client()
        res = client.api.bango.debug.get(
                data={'seller_product_bango':
                      self.app.app_payment_account.account_uri})
        filtered = {
            'bango': res['bango'],
        }
        return Response(filtered, status=200)
