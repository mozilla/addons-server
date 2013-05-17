import json

from curling.lib import HttpClientError, HttpServerError
import mock
from nose.tools import eq_

import amo
from amo.tests import app_factory
from addons.models import Addon, AddonUser
from users.models import UserProfile

from mkt.api.base import get_url, list_url
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.developers.models import PaymentAccount
from mkt.developers.tests.test_views_payments import setup_payment_account
from mkt.site.fixtures import fixture

package_data = {
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
    'account_name': 'account'
}

bank_data = {
    'bankAccountPayeeName': 'name',
    'bankAccountNumber': '123',
    'bankAccountCode': '123',
    'bankName': 'asd',
    'bankAddress1': 'address 2',
    'bankAddressZipCode': '123',
    'bankAddressIso': 'BRA',
}

payment_data = package_data.copy()
payment_data.update(bank_data)


class CreateAccountTests(BaseOAuth):

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


@mock.patch('mkt.developers.models.client')
class AccountTests(BaseOAuth):
    fixtures = BaseOAuth.fixtures + fixture('webapp_337141', 'user_999')

    def setUp(self):
        BaseOAuth.setUp(self, api_name='payments')
        self.app = Addon.objects.get(pk=337141)
        self.app.update(premium_type=amo.ADDON_FREE_INAPP)
        self.other = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.app, user=self.profile)
        self.account = setup_payment_account(self.app, self.profile,
                                             uid='uid2').payment_account
        self.account.name = 'account'
        self.account.save()

    def test_get_list(self, client):
        client.api.bango.package().get.return_value = {"full": payment_data}

        app2 = app_factory(premium_type=amo.ADDON_FREE_INAPP)
        AddonUser.objects.create(addon=app2, user=self.other)
        setup_payment_account(app2, self.other)

        r = self.client.get(list_url('account'))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        pkg = package_data.copy()
        pkg['resource_uri'] = '/api/v1/payments/account/%s/' % self.account.pk
        eq_(data['objects'], [pkg])

    def test_get(self, client):
        client.api.bango.package().get.return_value = {"full": payment_data}

        r = self.client.get(get_url('account', self.account.pk))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        pkg = package_data.copy()
        pkg['resource_uri'] = '/api/v1/payments/account/%s/' % self.account.pk
        eq_(data, pkg)

    def test_only_get_by_owner(self, client):
        r = self.anon.get(get_url('account', self.account.pk))
        eq_(r.status_code, 401)

    def test_put(self, client):
        addr = 'b@b.com'
        newpkg = package_data.copy()
        newpkg['adminEmailAddress'] = addr
        r = self.client.put(get_url('account', self.account.pk),
                            data=json.dumps(newpkg))
        eq_(r.status_code, 204)
        d = client.api.by_url().patch.call_args[1]['data']
        eq_(d['adminEmailAddress'], addr)

    def test_only_put_by_owner(self, client):
        app2 = app_factory(premium_type=amo.ADDON_FREE_INAPP)
        AddonUser.objects.create(addon=app2, user=self.other)
        acct = setup_payment_account(app2, self.other).payment_account
        r = self.client.put(get_url('account', acct.pk),
                            data=json.dumps(package_data))
        eq_(r.status_code, 404)

    def test_delete(self, client):
        rdel = self.client.delete(get_url('account', self.account.pk))
        eq_(rdel.status_code, 204)

        client.api.bango.package().get.return_value = {"full": payment_data}
        rget = self.client.get(list_url('account'))
        eq_(json.loads(rget.content)['objects'], [])
