import commonware.log

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from tastypie import http
from tastypie.authorization import Authorization
from tastypie.validation import CleanedDataFormValidation

import amo

from access.acl import check_ownership
from constants.payments import CONTRIB_NO_CHARGE
from lib.cef_loggers import receipt_cef
from lib.metrics import record_action
from market.models import AddonPurchase
from mkt.api.authentication import (OptionalOAuthAuthentication,
                                    SharedSecretAuthentication)
from mkt.api.base import CORSResource, http_error, MarketplaceResource
from mkt.api.http import HttpPaymentRequired
from mkt.constants import apps
from mkt.receipts.forms import ReceiptForm, TestInstall
from mkt.receipts.utils import create_receipt, create_test_receipt

from mkt.webapps.models import Installed


log = commonware.log.getLogger('z.receipt')


class ReceiptResource(CORSResource, MarketplaceResource):

    class Meta(MarketplaceResource.Meta):
        always_return_data = True
        authentication = (SharedSecretAuthentication(),
                          OptionalOAuthAuthentication())
        authorization = Authorization()
        detail_allowed_methods = []
        list_allowed_methods = ['post']
        object_class = dict
        resource_name = 'install'

    def obj_create(self, bundle, request=None, **kwargs):
        bundle.data['receipt'] = self.handle(bundle, request=request, **kwargs)
        amo.log(amo.LOG.INSTALL_ADDON, bundle.obj)
        record_action('install', request, {
            'app-domain': bundle.obj.domain_from_url(bundle.obj.origin,
                                                     allow_none=True),
            'app-id': bundle.obj.pk,
            'anonymous': request.user.is_anonymous(),
        })
        return bundle

    def handle(self, bundle, request, **kwargs):
        form = ReceiptForm(bundle.data)

        if not form.is_valid():
            raise self.form_errors(form)

        bundle.obj = form.cleaned_data['app']

        # Developers get handled quickly.
        if check_ownership(request, bundle.obj, require_owner=False,
                           ignore_disabled=True, admin=False):
            return self.record(bundle, request, apps.INSTALL_TYPE_DEVELOPER)

        # The app must be public and if its a premium app, you
        # must have purchased it.
        if not bundle.obj.is_public():
            log.info('App not public: %s' % bundle.obj.pk)
            raise http_error(http.HttpForbidden, 'App not public.')

        if (bundle.obj.is_premium() and
            not bundle.obj.has_purchased(request.amo_user)):
            # Apps that are premium but have no charge will get an
            # automatic purchase record created. This will ensure that
            # the receipt will work into the future if the price changes.
            if bundle.obj.premium and not bundle.obj.premium.price.price:
                log.info('Create purchase record: {0}'.format(bundle.obj.pk))
                AddonPurchase.objects.get_or_create(addon=bundle.obj,
                    user=request.amo_user, type=CONTRIB_NO_CHARGE)
            else:
                log.info('App not purchased: %s' % bundle.obj.pk)
                raise http_error(HttpPaymentRequired, 'You have not purchased this app.')

        # Anonymous users will fall through, they don't need anything else
        # handling.
        if request.user.is_authenticated():
            return self.record(bundle, request, apps.INSTALL_TYPE_USER)

    def record(self, bundle, request, install_type):
        # Generate or re-use an existing install record.
        installed, created = Installed.objects.get_or_create(
            addon=bundle.obj, user=request.user.get_profile(),
            install_type=install_type)

        log.info('Installed record %s: %s' % (
            'created' if created else 're-used',
            bundle.obj.pk))

        log.info('Creating receipt: %s' % bundle.obj.pk)
        receipt_cef.log(request, bundle.obj, 'sign', 'Receipt signing')
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


@api_view(['POST'])
@permission_classes((AllowAny,))
def reissue(request):
    # This is just a place holder for reissue that will hopefully return
    # a valid response, once reissue works. For the moment it doesn't. When
    # bug 757226 lands. For the moment just return a 200 and some text.
    return Response({'status': 'not-implemented', 'receipt': ''})
