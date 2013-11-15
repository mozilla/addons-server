import commonware.log

from rest_framework.decorators import (authentication_classes,
                                       permission_classes)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from tastypie.authorization import Authorization
from tastypie.validation import CleanedDataFormValidation


from constants.payments import CONTRIB_NO_CHARGE
from lib.cef_loggers import receipt_cef
from market.models import AddonPurchase
from mkt.api.authentication import (RestOAuthAuthentication,
                                    OptionalOAuthAuthentication,
                                    RestSharedSecretAuthentication)
from mkt.api.base import cors_api_view, CORSResource, MarketplaceResource
from mkt.constants import apps
from mkt.installs.utils import install_type, record
from mkt.receipts.forms import ReceiptForm, TestInstall
from mkt.receipts.utils import create_receipt, create_test_receipt

from mkt.webapps.models import Installed


log = commonware.log.getLogger('z.receipt')


@cors_api_view(['POST'])
@authentication_classes([RestOAuthAuthentication,
                         RestSharedSecretAuthentication])
@permission_classes([IsAuthenticated])
def install(request):
    form = ReceiptForm(request.DATA)

    if not form.is_valid():
        return Response({'error_message': form.errors}, status=400)

    obj = form.cleaned_data['app']
    type_ = install_type(request, obj)

    if type_ == apps.INSTALL_TYPE_DEVELOPER:
        receipt = install_record(obj, request,
                                 apps.INSTALL_TYPE_DEVELOPER)
    else:
        # The app must be public and if its a premium app, you
        # must have purchased it.
        if not obj.is_public():
            log.info('App not public: %s' % obj.pk)
            return Response('App not public.', status=403)

        if (obj.is_premium() and
            not obj.has_purchased(request.amo_user)):
            # Apps that are premium but have no charge will get an
            # automatic purchase record created. This will ensure that
            # the receipt will work into the future if the price changes.
            if obj.premium and not obj.premium.price.price:
                log.info('Create purchase record: {0}'.format(obj.pk))
                AddonPurchase.objects.get_or_create(addon=obj,
                    user=request.amo_user, type=CONTRIB_NO_CHARGE)
            else:
                log.info('App not purchased: %s' % obj.pk)
                return Response('You have not purchased this app.', status=402)
        receipt = install_record(obj, request, type_)
    record(request, obj)
    return Response({'receipt': receipt}, status=201)


def install_record(obj, request, install_type):
    # Generate or re-use an existing install record.
    installed, created = Installed.objects.get_or_create(
        addon=obj, user=request.user.get_profile(),
        install_type=install_type)

    log.info('Installed record %s: %s' % (
        'created' if created else 're-used',
        obj.pk))

    log.info('Creating receipt: %s' % obj.pk)
    receipt_cef.log(request._request, obj, 'sign', 'Receipt signing')
    return create_receipt(installed)


class TestReceiptResource(CORSResource, MarketplaceResource):

    class Meta(MarketplaceResource.Meta):
        always_return_data = True
        authentication = OptionalOAuthAuthentication()
        authorization = Authorization()
        detail_allowed_methods = []
        list_allowed_methods = ['post']
        object_class = dict
        resource_name = 'test'
        validation = CleanedDataFormValidation(form_class=TestInstall)

    def obj_create(self, bundle, request=None, **kwargs):
        receipt_cef.log(request, None, 'sign', 'Test receipt signing')
        bundle.data = {'receipt': create_test_receipt(
            bundle.data['root'], bundle.data['receipt_type'])}
        return bundle


@cors_api_view(['POST'])
@permission_classes((AllowAny,))
def reissue(request):
    # This is just a place holder for reissue that will hopefully return
    # a valid response, once reissue works. For the moment it doesn't. When
    # bug 757226 lands. For the moment just return a 200 and some text.
    return Response({'status': 'not-implemented', 'receipt': ''})
