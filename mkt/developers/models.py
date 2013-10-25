import posixpath
import uuid

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import models

import commonware.log
from tower import ugettext_lazy as _lazy

import amo
from amo.urlresolvers import reverse
from lib.crypto import generate_key
from lib.pay_server import client
from mkt.constants.payments import ACCESS_PURCHASE, ACCESS_SIMULATE
from mkt.purchase import webpay
from users.models import UserForeignKey

log = commonware.log.getLogger('z.devhub')


def uri_to_pk(uri):
    """
    Convert a resource URI to the primary key of the resource.
    """
    return uri.rstrip('/').split('/')[-1]


class SolitudeSeller(amo.models.ModelBase):
    # TODO: When Solitude allows for it, this should be updated to be 1:1 with
    # users.
    user = UserForeignKey()
    uuid = models.CharField(max_length=255, unique=True)
    resource_uri = models.CharField(max_length=255)

    class Meta:
        db_table = 'payments_seller'

    @classmethod
    def create(cls, user):
        uuid_ = str(uuid.uuid4())
        res = client.api.generic.seller.post(data={'uuid': uuid_})
        uri = res['resource_uri']
        obj = cls.objects.create(user=user, uuid=uuid_, resource_uri=uri)

        log.info('[User:%s] Created Solitude seller (uuid:%s)' %
                     (user, uuid_))
        return obj


class PaymentAccount(amo.models.ModelBase):
    user = UserForeignKey()
    name = models.CharField(max_length=64)
    agreed_tos = models.BooleanField()
    solitude_seller = models.ForeignKey(SolitudeSeller)

    # These two fields can go away when we're not 1:1 with SolitudeSellers.
    seller_uri = models.CharField(max_length=255, unique=True)
    uri = models.CharField(max_length=255, unique=True)
    # A soft-delete so we can talk to Solitude asynchronously.
    inactive = models.BooleanField(default=False)
    bango_package_id = models.IntegerField(blank=True, null=True)

    shared = models.BooleanField(default=False)

    BANGO_PACKAGE_VALUES = (
        'adminEmailAddress', 'supportEmailAddress', 'financeEmailAddress',
        'paypalEmailAddress', 'vendorName', 'companyName', 'address1',
        'addressCity', 'addressState', 'addressZipCode', 'addressPhone',
        'countryIso', 'currencyIso', 'vatNumber')
    BANGO_BANK_DETAILS_VALUES = (
        'seller_bango', 'bankAccountPayeeName', 'bankAccountNumber',
        'bankAccountCode', 'bankName', 'bankAddress1', 'bankAddressZipCode',
        'bankAddressIso', )

    class Meta:
        db_table = 'payment_accounts'
        unique_together = ('user', 'uri')

    @classmethod
    def create_bango(cls, user, form_data):
        # Get the seller object.
        user_seller = SolitudeSeller.create(user)

        # Get the data together for the package creation.
        package_values = dict((k, v) for k, v in form_data.items() if
                              k in cls.BANGO_PACKAGE_VALUES)
        # Dummy value since we don't really use this.
        package_values.setdefault('paypalEmailAddress', 'nobody@example.com')
        package_values['seller'] = user_seller.resource_uri

        log.info('[User:%s] Creating Bango package' % user)
        res = client.api.bango.package.post(data=package_values)
        uri = res['resource_uri']

        # Get the data together for the bank details creation.
        bank_details_values = dict((k, v) for k, v in form_data.items() if
                                   k in cls.BANGO_BANK_DETAILS_VALUES)
        bank_details_values['seller_bango'] = uri

        log.info('[User:%s] Creating Bango bank details' % user)
        client.api.bango.bank.post(data=bank_details_values)

        obj = cls.objects.create(user=user, uri=uri,
                                 solitude_seller=user_seller,
                                 seller_uri=user_seller.resource_uri,
                                 bango_package_id=res['package_id'],
                                 name=form_data['account_name'])

        log.info('[User:%s] Created Bango payment account (uri: %s)' %
                     (user, uri))
        return obj

    def cancel(self, disable_refs=False):
        """Cancels the payment account.

        If `disable_refs` is set, existing apps that use this payment account
        will be set to STATUS_NULL.

        """
        self.update(inactive=True)
        log.info('[1@None] Soft-deleted payment account (uri: %s)' %
                     self.uri)

        account_refs = AddonPaymentAccount.objects.filter(account_uri=self.uri)
        for acc_ref in account_refs:
            if disable_refs:
                log.info('Changing app status to NULL for app: {0}'
                         'because of payment account deletion'.format(
                             acc_ref.addon_id))

                acc_ref.addon.update(status=amo.STATUS_NULL)
            log.info('Deleting AddonPaymentAccount for app: {0} because of '
                     'payment account deletion'.format(acc_ref.addon_id))
            acc_ref.delete()

    def update_account_details(self, **kwargs):
        self.update(name=kwargs.pop('account_name'))
        client.api.by_url(self.uri).patch(
            data=dict((k, v) for k, v in kwargs.items() if
                      k in self.BANGO_PACKAGE_VALUES))

    def get_details(self):
        data = {'account_name': self.name}
        package_data = (client.api.bango.package(uri_to_pk(self.uri))
                        .get(data={'full': True}))
        data.update((k, v) for k, v in package_data.get('full').items() if
                    k in self.BANGO_PACKAGE_VALUES)
        return data

    def __unicode__(self):
        return u'%s - %s' % (self.created.strftime('%m/%y'), self.name)

    def get_agreement_url(self):
        return reverse('mkt.developers.bango.agreement', args=[self.pk])

    def get_lookup_portal_url(self):
        return reverse('lookup.bango_portal_from_package',
                       args=[self.bango_package_id])


class AddonPaymentAccount(amo.models.ModelBase):
    addon = models.OneToOneField(
        'addons.Addon', related_name='app_payment_account')
    payment_account = models.ForeignKey(PaymentAccount)
    provider = models.CharField(
        max_length=8, choices=[('bango', _lazy('Bango'))])
    account_uri = models.CharField(max_length=255)
    product_uri = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'addon_payment_account'

    @classmethod
    def create(cls, provider, addon, payment_account):
        # TODO: remove once API is the only access point.
        uri = cls.setup_bango(provider, addon, payment_account)
        return cls.objects.create(addon=addon, provider=provider,
                                  payment_account=payment_account,
                                  account_uri=payment_account.uri,
                                  product_uri=uri)

    @classmethod
    def setup_bango(cls, provider, addon, payment_account):
        secret = generate_key(48)
        external_id = webpay.make_ext_id(addon.pk)
        data = {'seller': uri_to_pk(payment_account.seller_uri),
                'external_id': external_id}
        try:
            generic_product = client.api.generic.product.get_object(**data)
        except ObjectDoesNotExist:
            generic_product = client.api.generic.product.post(data={
                'seller': payment_account.seller_uri, 'secret': secret,
                'external_id': external_id, 'public_id': str(uuid.uuid4()),
                'access': ACCESS_PURCHASE,
            })

        product_uri = generic_product['resource_uri']
        if provider == 'bango':
            uri = cls._create_bango(
                product_uri, addon, payment_account, secret)
        else:
            uri = ''
        return uri

    @classmethod
    def _create_bango(cls, product_uri, addon, payment_account, secret):
        if not payment_account.bango_package_id:
            raise NotImplementedError('Currently we only support Bango '
                                      'so the associated account must '
                                      'have a bango_package_id')
        res = None
        if product_uri:
            data = {'seller_product': uri_to_pk(product_uri)}
            try:
                res = client.api.bango.product.get_object(**data)
            except ObjectDoesNotExist:
                # The product does not exist in Solitude so create it.
                res = client.api.bango.product.post(data={
                    'seller_bango': payment_account.uri,
                    'seller_product': product_uri,
                    'name': unicode(addon.name),
                    'packageId': payment_account.bango_package_id,
                    'categoryId': 1,
                    'secret': secret
                })

        product_uri = res['resource_uri']
        bango_number = res['bango_id']

        # If the app is already premium this does nothing.
        if addon.premium_type != amo.ADDON_FREE_INAPP:
            cls._push_bango_premium(bango_number, product_uri,
                                    addon.addonpremium.price.price)

        return product_uri

    @classmethod
    def _push_bango_premium(cls, bango_number, product_uri, price):
        if price != 0:
            # Make the Bango product premium.
            client.api.bango.premium.post(
                data={'bango': bango_number,
                      'price': price,
                      'currencyIso': 'USD',
                      'seller_product_bango': product_uri})

        # Update the Bango rating.
        client.api.bango.rating.post(
            data={'bango': bango_number,
                  'rating': 'UNIVERSAL',
                  'ratingScheme': 'GLOBAL',
                  'seller_product_bango': product_uri})
        # Bug 836865.
        client.api.bango.rating.post(
            data={'bango': bango_number,
                  'rating': 'GENERAL',
                  'ratingScheme': 'USA',
                  'seller_product_bango': product_uri})

        return product_uri

    def update_price(self, new_price):
        if self.provider == 'bango':
            # Get the Bango number for this product.
            res = client.api.by_url(self.product_uri).get_object()
            bango_number = res['bango_id']

            AddonPaymentAccount._push_bango_premium(
                bango_number, self.product_uri, new_price)

    def delete(self):
        if self.provider == 'bango':
            # TODO(solitude): Once solitude supports DeleteBangoNumber, that
            # goes here.
            # ...also, make it a (celery) task.

            # client.delete_product_bango(self.product_uri)
            pass

        super(AddonPaymentAccount, self).delete()


class UserInappKey(amo.models.ModelBase):
    solitude_seller = models.ForeignKey(SolitudeSeller)
    seller_product_pk = models.IntegerField(unique=True)

    def secret(self):
        return self._product().get()['secret']

    def public_id(self):
        return self._product().get()['public_id']

    def reset(self):
        self._product().patch(data={'secret': generate_key(48)})

    @classmethod
    def create(cls, user):
        sel = SolitudeSeller.create(user)
        # Create a product key that can only be used for simulated purchases.
        prod = client.api.generic.product.post(data={
            'seller': sel.resource_uri, 'secret': generate_key(48),
            'external_id': str(uuid.uuid4()), 'public_id': str(uuid.uuid4()),
            'access': ACCESS_SIMULATE,
        })
        log.info('User %s created an in-app payments dev key product=%s '
                 'with %s' % (user, prod['resource_pk'], sel))
        return cls.objects.create(solitude_seller=sel,
                                  seller_product_pk=prod['resource_pk'])

    def _product(self):
        return client.api.generic.product(self.seller_product_pk)

    class Meta:
        db_table = 'user_inapp_keys'


class PreloadTestPlan(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon')
    last_submission = models.DateTimeField(auto_now_add=True)
    filename = models.CharField(max_length=60)
    status = models.PositiveSmallIntegerField(default=amo.STATUS_PUBLIC)

    class Meta:
        db_table = 'preload_test_plans'
        ordering = ['-last_submission']

    @property
    def preload_test_plan_url(self):
        host = (settings.PRIVATE_MIRROR_URL if self.addon.is_disabled
                else settings.LOCAL_MIRROR_URL)
        return posixpath.join(host, str(self.addon.id), self.filename)
