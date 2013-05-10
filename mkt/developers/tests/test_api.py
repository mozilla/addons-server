import json

import mock
from nose.tools import eq_

from mkt.api.tests.test_oauth import BaseOAuth, get_absolute_url
from mkt.api.base import list_url
from mkt.developers.models import PaymentAccount


class AccountTests(BaseOAuth):

    def setUp(self):
        BaseOAuth.setUp(self, api_name='payments')

    @mock.patch('mkt.developers.models.client')
    def test_add(self, client):
        data = {
            'bankAccountPayeeName': 'name',
            'companyName': 'company',
            'vendorName': 'vendor',
            'financeEmailAddress': 'a@a.com',
            'adminEmailAddress': 'a@a.com',
            'supportEmailAddress': 'a@a.com',
            'address1': 'address 1',
            'addressCity': 'city',
            'addressState': 'state',
            'addressZipCode': 'zip',
            'addressPhone': '123',
            'countryIso': 'BRA',
            'currencyIso': 'EUR',
            'bankAccountNumber': '123',
            'bankAccountCode': '123',
            'bankName': 'asd',
            'bankAddress1': 'address 2',
            'bankAddressZipCode': '123',
            'bankAddressIso': 'BRA',
            'account_name': 'account'
        }
        r = self.client.post(list_url('account'),
                             data=json.dumps(data))
        eq_(r.status_code, 201)
        pa = PaymentAccount.objects.get(name='account')
        eq_(pa.user.pk, self.user.pk)
        d = client.api.bango.package.post.call_args[1]['data']
        for k, v in d.iteritems():
            if k not in ['paypalEmailAddress', 'seller']:
                eq_(data[k], v)
