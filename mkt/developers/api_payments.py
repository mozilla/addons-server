from rest_framework.mixins import (CreateModelMixin, DestroyModelMixin,
                                   RetrieveModelMixin, UpdateModelMixin)
from rest_framework.permissions import BasePermission
from rest_framework.relations import HyperlinkedRelatedField
from rest_framework.serializers import (HyperlinkedModelSerializer,
                                        ValidationError)
from rest_framework.viewsets import GenericViewSet
from django.core.exceptions import PermissionDenied

import amo
from addons.models import AddonUpsell

from mkt.api.base import CompatRelatedField
from mkt.api.authorization import AllowAppOwner
from mkt.webapps.models import Webapp


class PaymentSerializer(HyperlinkedModelSerializer):
    upsell = HyperlinkedRelatedField(read_only=True,
                                     view_name='app-upsell-detail')

    class Meta:
        model = Webapp
        fields = ('upsell',)
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
        fields = ('free', 'premium', 'created', 'modified')
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
    permission_classes = (UpsellPermission,)
    queryset = AddonUpsell.objects.filter()
    serializer_class = UpsellSerializer

    def pre_save(self, obj):
        if not UpsellPermission().check(self.request, obj.free, obj.premium):
            raise PermissionDenied('Not allowed to alter that object')
