
import uuid

from django.db import models

import commonware.log
from tower import ugettext_lazy as _lazy

import amo
from devhub.models import ActivityLog
from lib.crypto import generate_key
from lib.pay_server import client
from users.models import UserForeignKey

log = commonware.log.getLogger('z.devhub')


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
        # TODO(solitude): This could probably be made asynchronous.
        res = client.post_seller(data={'uuid': uuid_})
        uri = res['resource_uri']
        obj = cls.objects.create(user=user, uuid=uuid_, resource_uri=uri)

        log.info('[User:%s] Created Solitude seller (uuid:%s)' %
                     (user, uuid_))
        return obj


# BlueVia

class BlueViaConfig(amo.models.ModelBase):
    user = UserForeignKey()
    developer_id = models.CharField(max_length=64)

    class Meta:
        db_table = 'bluevia'
        unique_together = ('user', 'developer_id')


class AddonBlueViaConfig(amo.models.ModelBase):
    addon = models.OneToOneField('addons.Addon',
                                 related_name='addonblueviaconfig')
    bluevia_config = models.ForeignKey(BlueViaConfig)
    status = models.PositiveIntegerField(choices=amo.INAPP_STATUS_CHOICES,
                                         default=amo.INAPP_STATUS_INACTIVE,
                                         db_index=True)

    class Meta:
        db_table = 'addon_bluevia'
        unique_together = ('addon', 'bluevia_config')


class PaymentAccount(amo.models.ModelBase):
    user = UserForeignKey()
    name = models.CharField(max_length=64)

    # These two fields can go away when we're not 1:1 with SolitudeSellers.
    seller_uri = models.CharField(max_length=255, unique=True)
    uri = models.CharField(max_length=255, unique=True)
    # A soft-delete so we can talk to Solitude asynchronously.
    inactive = models.BooleanField(default=False)

    BANGO_PACKAGE_VALUES = (
        'adminEmailAddress', 'supportEmailAddress', 'financeEmailAddress',
        'paypalEmailAddress', 'vendorName', 'companyName', 'address1',
        'addressCity', 'addressState', 'addressZipCode', 'addressPhone',
        'countryIso', 'currencyIso', )
    BANGO_BANK_DETAILS_VALUES = (
        'seller_bango', 'bankAccountPayeeName', 'bankAccountNumber',
        'bankAccountCode', 'bankName', 'bankAddress1', 'bankAddressZipCode',
        'bankAddressIso', )

    class Meta:
        db_table = 'payment_accounts'
        unique_together = ('user', 'uri')

    # TODO(solitude): Make this async.
    @classmethod
    def create_bango(cls, user, form_data):
        # Get the seller object.
        # TODO(solitude): When solitude supports multiple packages per seller,
        # change this to .get_or_create(user).
        user_seller = SolitudeSeller.create(user)

        # Get the data together for the package creation.
        package_values = dict((k, v) for k, v in form_data.items() if
                              k in cls.BANGO_PACKAGE_VALUES)
        # TODO: Fill these with better values?
        package_values.setdefault('supportEmailAddress', 'support@example.com')
        package_values.setdefault('paypalEmailAddress', 'nobody@example.com')
        package_values['seller'] = user_seller.resource_uri

        log.info('[User:%s] Creating Bango package' % user)
        res = client.post_package(data=package_values)
        uri = res['resource_uri']

        # Get the data together for the bank details creation.
        bank_details_values = dict((k, v) for k, v in form_data.items() if
                                   k in cls.BANGO_BANK_DETAILS_VALUES)
        bank_details_values['seller_bango'] = uri

        log.info('[User:%s] Creating Bango bank details' % user)
        client.post_bank_details(data=bank_details_values)

        obj = cls.objects.create(user=user, uri=uri,
                                 seller_uri=user_seller.resource_uri,
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
                acc_ref.addon.update(status=amo.STATUS_NULL)
            acc_ref.delete()

        # TODO(solitude): Once solitude supports CancelPackage, that goes here.
        # ...also, make it a (celery) task.

        # We would otherwise have delete(), but we don't want to do that
        # without CancelPackage-ing. Once that support is added, we can write a
        # migration to re-cancel and hard delete the inactive objects.

    def __unicode__(self):
        return u'%s - %s' % (self.created.strftime('%m/%y'), self.name)


class AddonPaymentAccount(amo.models.ModelBase):
    addon = models.OneToOneField(
        'addons.Addon', related_name='app_payment_account')
    provider = models.CharField(
        max_length=8, choices=[('bango', _lazy('Bango'))])
    account_uri = models.CharField(max_length=255)
    product_uri = models.CharField(max_length=255, unique=True)

    # The set_price is the price that the product was created at. This lets us
    # figure out whether we need to post an update to Solitude when the price
    # of the app changes.
    set_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'addon_payment_account'

    @classmethod
    def create(cls, provider, addon, payment_account):
        """Parameters:

        - provider:
            The provider that the product is to be created for. (currently only
            `bango`)
        - addon:
            The app that the product is being created for.
        - payment_account:
            The PaymentAccount object to tie the app to.

        """
        secret = generate_key(48)
        generic_product = client.upsert(
            method='product',
            params={'seller': payment_account.seller_uri, 'secret': secret,
                    'external_id': addon.pk},
            lookup_by=['external_id'])
        product_uri = generic_product['resource_uri']

        if provider == 'bango':
            uri = cls._create_bango(
                product_uri, addon, payment_account, secret)
        else:
            uri = ''

        return cls.objects.create(addon=addon, provider=provider,
                                  set_price=addon.premium.price.price,
                                  account_uri=payment_account.uri,
                                  product_uri=uri)

    @classmethod
    def _create_bango(cls, product_uri, addon, payment_account, secret):
        # Create the Bango product via Solitude.
        res = client.upsert(
            method='product_bango',
            params={'seller_bango': payment_account.uri,
                    'seller_product': product_uri,
                    'name': addon.name,
                    'categoryId': 1,
                    'secret': secret},
            lookup_by=['seller_product'])
        product_uri = res['resource_uri']
        bango_number = res['bango_id']

        cls._push_bango_premium(
            bango_number, product_uri, float(addon.premium.price.price))

        return product_uri

    @classmethod
    def _push_bango_premium(cls, bango_number, product_uri, price):
        # Make the Bango product premium.
        client.post_make_premium(
            data={'bango': bango_number,
                  'price': price,
                  'currencyIso': 'USD',
                  'seller_product_bango': product_uri})

        # Update the Bango rating.
        client.post_update_rating(
            data={'bango': bango_number,
                  'rating': 'UNIVERSAL',
                  'ratingScheme': 'GLOBAL',
                  'seller_product_bango': product_uri})

        return product_uri

    def update_price(self, new_price):
        # Ignore the update if it's the same as what we've got.
        if new_price == self.set_price:
            return

        if self.provider == 'bango':
            # Get the Bango number for this product.
            res = client.get_product_bango(data=self.product_uri)
            bango_number = res['bango']

            AddonPaymentAccount._push_bango_premium(
                bango_number, self.product_uri, new_price)

            self.update(set_price=new_price)

    def delete(self):
        if self.provider == 'bango':
            # TODO(solitude): Once solitude supports DeleteBangoNumber, that
            # goes here.
            # ...also, make it a (celery) task.

            # client.delete_product_bango(self.product_uri)
            pass

        super(AddonPaymentAccount, self).delete()
