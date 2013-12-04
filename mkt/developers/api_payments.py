from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse

import commonware
from curling.lib import HttpClientError, HttpServerError
from rest_framework import status
from rest_framework.mixins import (CreateModelMixin, DestroyModelMixin,
                                   ListModelMixin, RetrieveModelMixin,
                                   UpdateModelMixin)
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.relations import HyperlinkedRelatedField
from rest_framework.response import Response
from rest_framework.serializers import (HyperlinkedModelSerializer,
                                        Serializer,
                                        ValidationError)
from rest_framework.viewsets import GenericViewSet
from tower import ugettext as _

import amo
from addons.models import AddonUpsell

from mkt.api.authorization import (AllowAppOwner, GroupPermission,
                                   switch)
from mkt.api.authentication import (RestOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.base import AppViewSet, MarketplaceView
from mkt.constants.payments import PAYMENT_STATUSES
from mkt.developers.forms_payments import (BangoPaymentAccountForm,
                                           PaymentCheckForm)
from mkt.developers.models import (AddonPaymentAccount, CantCancel,
                                   PaymentAccount)
from mkt.developers.providers import get_provider
from mkt.webapps.models import Webapp


from lib.pay_server import get_client

log = commonware.log.getLogger('z.api.payments')


class PaymentAccountSerializer(Serializer):
    """
    Fake serializer that returns PaymentAccount details when
    serializing a PaymentAccount instance. Use only for read operations.
    """
    def to_native(self, obj):
        data = obj.get_provider().account_retrieve(obj)
        data['resource_uri'] = reverse('payment-account-detail',
                                       kwargs={'pk': obj.pk})
        return data


class PaymentAccountViewSet(ListModelMixin, RetrieveModelMixin,
                            MarketplaceView, GenericViewSet):
    queryset = PaymentAccount.objects.all()
    # PaymentAccountSerializer is not a real serializer, it just looks up
    # the details on the object. It's only used for GET requests, in every
    # other case we use BangoPaymentAccountForm directly.
    serializer_class = PaymentAccountSerializer
    authentication_classes = [RestOAuthAuthentication,
                              RestSharedSecretAuthentication]
    # Security checks are performed in get_queryset(), so we allow any
    # authenticated users by default.
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """
        Return the queryset specific to the user using the view. (This replaces
        permission checks, unauthorized users won't be able to see that an
        account they don't have access to exists, we'll return 404 for them.)
        """
        qs = super(PaymentAccountViewSet, self).get_queryset()
        return qs.filter(user=self.request.amo_user, inactive=False)

    def create(self, request, *args, **kwargs):
        provider = get_provider()
        form = provider.forms['account'](request.DATA)
        if form.is_valid():
            try:
                provider = get_provider()
                obj = provider.account_create(request.amo_user, form.data)
            except HttpClientError as e:
                log.error('Client error creating Bango account; %s' % e)
                return Response(e.content,
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except HttpServerError as e:
                log.error('Error creating Bango payment account; %s' % e)
                return Response(_(u'Could not connect to payment server.'),
                               status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            serializer = self.get_serializer(obj)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

    def partial_update(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def update(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = BangoPaymentAccountForm(request.DATA, account=True)
        if form.is_valid():
            self.object.get_provider().account_update(self.object, form.cleaned_data)
            return Response(status=status.HTTP_204_NO_CONTENT)

        return Response(form.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        account = self.get_object()
        try:
            account.cancel(disable_refs=True)
        except CantCancel:
            return Response(_('Cannot delete shared account'),
                            status=status.HTTP_409_CONFLICT)
        log.info('Account cancelled: %s' % account.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


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


class PaymentViewSet(RetrieveModelMixin, MarketplaceView, GenericViewSet):
    permission_classes = (AllowAppOwner,)
    queryset = Webapp.objects.filter()
    serializer_class = PaymentSerializer


class UpsellSerializer(HyperlinkedModelSerializer):
    free = premium = HyperlinkedRelatedField(view_name='app-detail')

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
                    UpdateModelMixin, MarketplaceView, GenericViewSet):
    permission_classes = (switch('allow-b2g-paid-submission'),
                          UpsellPermission,)
    queryset = AddonUpsell.objects.filter()
    serializer_class = UpsellSerializer

    def pre_save(self, obj):
        if not UpsellPermission().check(self.request, obj.free, obj.premium):
            raise PermissionDenied('Not allowed to alter that object')


class AddonPaymentAccountPermission(BasePermission):
    """
    Permissions on the app payment account object, is determined by permissions
    on the app the account is being used for.
    """

    def check(self, request, app, account):
        if AllowAppOwner().has_object_permission(request, '', app):
            if account.shared or account.user.pk == request.amo_user.pk:
                return True
            else:
                log.info('AddonPaymentAccount access %(account)s denied '
                         'for %(user)s: wrong user, not shared.'.format(
                         {'account': account.pk, 'user': request.amo_user.pk}))
        else:
            log.info('AddonPaymentAccount access %(account)s denied '
                     'for %(user)s: no app permission.'.format(
                     {'account': account.pk, 'user': request.amo_user.pk}))
        return False

    def has_object_permission(self, request, view, object):
        return self.check(request, object.addon, object.payment_account)


class AddonPaymentAccountSerializer(HyperlinkedModelSerializer):
    addon = HyperlinkedRelatedField(view_name='app-detail')
    payment_account = HyperlinkedRelatedField(
        view_name='payment-account-detail')
    class Meta:
        model = AddonPaymentAccount
        fields = ('addon', 'payment_account', 'provider',
                  'created', 'modified', 'url')
        view_name = 'app-payment-account-detail'

    def validate(self, attrs):
        if attrs['addon'].premium_type in amo.ADDON_FREES:
            raise ValidationError('App must be a premium app.')

        return attrs


class AddonPaymentAccountViewSet(CreateModelMixin, RetrieveModelMixin,
                                 UpdateModelMixin, MarketplaceView,
                                 GenericViewSet):
    permission_classes = (AddonPaymentAccountPermission,)
    queryset = AddonPaymentAccount.objects.filter()
    serializer_class = AddonPaymentAccountSerializer

    def pre_save(self, obj):
        if not AddonPaymentAccountPermission().check(self.request,
                obj.addon, obj.payment_account):
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
    permission_classes = [GroupPermission('Transaction', 'Debug')]
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
