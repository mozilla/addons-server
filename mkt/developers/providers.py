import os
import uuid

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

import commonware

from constants.payments import PROVIDER_BANGO, PROVIDER_REFERENCE
from lib.pay_server import client
from mkt.developers import forms_payments
from mkt.developers.models import PaymentAccount, SolitudeSeller


root = 'developers/payments/includes/'

log = commonware.log.getLogger('z.devhub.providers')


class Provider(object):

    def account_create(self, user, form_data):
        raise NotImplementedError

    def setup_seller(self, user):
        log.info('[User:{0}] Creating seller'.format(user.pk))
        return SolitudeSeller.create(user)

    def setup_account(self, **kw):
        log.info('[User:{0}] Created payment account (uri: {1})'
                 .format(kw['user'].pk, kw['uri']))
        kw.update({'seller_uri': kw['solitude_seller'].resource_uri,
                   'provider': self.provider})
        return PaymentAccount.objects.create(**kw)


class Bango(Provider):
    client = client.api.bango
    name = 'bango'
    provider = PROVIDER_BANGO
    templates = {
        'add': os.path.join(root, 'add_payment_account_bango.html'),
        'edit': os.path.join(root, 'edit_payment_account_bango.html'),
    }
    forms = {
        'account': forms_payments.BangoPaymentAccountForm,
    }

    package_values = (
        'adminEmailAddress', 'supportEmailAddress', 'financeEmailAddress',
        'paypalEmailAddress', 'vendorName', 'companyName', 'address1',
        'address2', 'addressCity', 'addressState', 'addressZipCode',
        'addressPhone', 'countryIso', 'currencyIso', 'vatNumber'
    )
    bank_values = (
        'seller_bango', 'bankAccountPayeeName', 'bankAccountNumber',
        'bankAccountCode', 'bankName', 'bankAddress1', 'bankAddress2',
        'bankAddressZipCode', 'bankAddressIso'
    )

    def account_create(self, user, form_data):
        # Get the seller object.
        user_seller = self.setup_seller(user)

        # Get the data together for the package creation.
        package_values = dict((k, v) for k, v in form_data.items() if
                              k in self.package_values)
        # Dummy value since we don't really use this.
        package_values.setdefault('paypalEmailAddress', 'nobody@example.com')
        package_values['seller'] = user_seller.resource_uri

        log.info('[User:%s] Creating Bango package' % user)
        res = self.client.package.post(data=package_values)
        uri = res['resource_uri']

        # Get the data together for the bank details creation.
        bank_details_values = dict((k, v) for k, v in form_data.items() if
                                   k in self.bank_values)
        bank_details_values['seller_bango'] = uri

        log.info('[User:%s] Creating Bango bank details' % user)
        self.client.bank.post(data=bank_details_values)
        return self.setup_account(user=user,
                                  uri=res['resource_uri'],
                                  solitude_seller=user_seller,
                                  account_id=res['package_id'],
                                  name=form_data['account_name'])


class Reference(Provider):
    client = client.api.provider.reference
    name = 'reference'
    provider = PROVIDER_REFERENCE
    templates = {
        'add': os.path.join(root, 'add_payment_account_reference.html'),
        'edit': os.path.join(root, 'edit_payment_account_reference.html'),
    }
    forms = {
        'account': forms_payments.ReferenceAccountForm,
    }

    def account_create(self, user, form_data):
        user_seller = self.setup_seller(user)
        form_data.update({'uuid': str(uuid.uuid4()), 'status': 'ACTIVE'})
        name = form_data.pop('account_name')
        res = self.client.sellers.post(data=form_data)
        return self.setup_account(user=user,
                                  uri=res['resource_uri'],
                                  solitude_seller=user_seller,
                                  account_id=res['resource_pk'],
                                  name=name)


ALL_PROVIDERS = dict((l.name, l) for l in (Bango(), Reference()))


def get_provider():
    if len(settings.PAYMENT_PROVIDERS) != 1:
        raise ImproperlyConfigured('You must have only one payment provider '
            'in zamboni. Having multiple providers at one time will be added '
            'at a later date.')
    return ALL_PROVIDERS[settings.PAYMENT_PROVIDERS[0]]
