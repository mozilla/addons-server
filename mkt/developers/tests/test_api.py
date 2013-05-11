import json

from curling.lib import HttpClientError, HttpServerError
import mock
from nose.tools import eq_

from mkt.api.base import list_url
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.developers.models import PaymentAccount

payment_data = {
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


class AccountTests(BaseOAuth):

    def setUp(self):
        BaseOAuth.setUp(self, api_name='payments')

    @mock.patch('mkt.developers.models.client')
    def test_add(self, client):
        r = self.client.post(list_url('account'),
                             data=json.dumps(payment_data))
        eq_(r.status_code, 201)
        pa = PaymentAccount.objects.get(name='account')
        eq_(pa.user.pk, self.user.pk)
        d = client.api.bango.package.post.call_args[1]['data']
        for k, v in d.iteritems():
            if k not in ['paypalEmailAddress', 'seller']:
                eq_(payment_data[k], v)

    @mock.patch('mkt.developers.models.client')
    def test_add_fail(self, client):
        err = {'broken': True}
        client.api.bango.package.post.side_effect = HttpClientError(
            content=err)
        r = self.client.post(list_url('account'),
                             data=json.dumps(payment_data))
        eq_(r.status_code, 500)
        eq_(json.loads(r.content), err)

    @mock.patch('mkt.developers.models.client')
    def test_add_fail2(self, client):
        client.api.bango.package.post.side_effect = HttpServerError()
        r = self.client.post(list_url('account'),
                             data=json.dumps(payment_data))
        eq_(r.status_code, 500)
