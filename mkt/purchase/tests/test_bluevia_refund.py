from decimal import Decimal
import json

import mock
from nose.tools import eq_

import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from lib.crypto.bluevia import sign_bluevia_jwt
from mkt.purchase.tests.samples import refund
from stats.models import Contribution
from users.models import UserProfile


class SalesTest(object):

    def setUp(self):
        self.app = Addon.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=999)
        self.sale = Contribution.objects.create(
                            addon=self.app, amount=Decimal(1),
                            bluevia_transaction_id='1',
                            type=amo.CONTRIB_PURCHASE, user=self.user)


class TestRefund(SalesTest, amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube', 'base/users']

    def setUp(self):
        super(TestRefund, self).setUp()
        self.url = reverse('bluevia.prepare_refund',
                           args=[self.app.app_slug, '1'])
        self.client.login(username='regular@mozilla.com', password='password')

    def test_logged_out(self):
        self.client.logout()
        self.assertLoginRequired(self.client.post(self.url))

    def test_wrong_uid(self):
        url = reverse('bluevia.prepare_refund',
                      args=[self.app.app_slug, '4'])
        eq_(self.client.post(url).status_code, 400)

    def test_not_mine(self):
        self.sale.update(user=UserProfile.objects.get(pk=10482))
        eq_(self.client.post(self.url).status_code, 400)

    def test_not_purchase(self):
        self.sale.update(type=amo.CONTRIB_REFUND)
        eq_(self.client.post(self.url).status_code, 400)

    @mock.patch('apps.stats.models.Contribution.is_instant_refund')
    def test_not_instant(self, is_instant_refund):
        is_instant_refund.return_value = False
        eq_(self.client.post(self.url).status_code, 400)

    def test_success(self):
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        assert 'blueviaJWT' in json.loads(res.content)


class TestPostback(SalesTest, amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube', 'base/users']

    def setUp(self):
        super(TestPostback, self).setUp()
        self.url = reverse('bluevia.chargeback')

    @mock.patch('lib.crypto.bluevia.verify_bluevia_jwt')
    def test_not_valid(self, verify_bluevia_jwt):
        verify_bluevia_jwt.return_value = {'valid': False}
        eq_(self.client.post(self.url).status_code, 400)

    @mock.patch('mkt.purchase.bluevia.parse_from_bluevia')
    def test_wrong_uid(self, parse_from_bluevia):
        parse_from_bluevia.return_value = {'response':
                                            {'transactionID': '4'}}
        eq_(self.client.post(self.url).status_code, 400)

    @mock.patch('mkt.purchase.bluevia.parse_from_bluevia')
    def test_parsed(self, parse_from_bluevia):
        parse_from_bluevia.return_value = {'response':
                                            {'transactionID': '1'}}
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.sale.is_refunded(), True)

        refunds = Contribution.objects.filter(type=amo.CONTRIB_REFUND)
        eq_(len(refunds), 1)

        refund = refunds[0]
        eq_(refund.amount, -self.sale.amount)
        eq_(refund.bluevia_transaction_id, None)
        eq_(refund.related, self.sale)

    @mock.patch('mkt.purchase.bluevia.parse_from_bluevia')
    def test_purchased(self, parse_from_bluevia):
        # Just a double check that receipts will be invalid.
        parse_from_bluevia.return_value = {'response':
                                            {'transactionID': '1'}}

        eq_(self.app.has_purchased(self.user), True)
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.app.has_purchased(self.user), False)
        eq_(self.app.is_refunded(self.user), True)

    def test_encode(self):
        data = sign_bluevia_jwt(refund)
        res = self.client.post(self.url, data, content_type='application/json')
        eq_(res.status_code, 200)
        eq_(self.sale.is_refunded(), True)

    @mock.patch('mkt.purchase.bluevia_tasks._notify')
    def test_notifies(self, _notify):
        data = sign_bluevia_jwt(refund)
        res = self.client.post(self.url, data, content_type='application/json')
        eq_(res.status_code, 200)
        assert _notify.called
