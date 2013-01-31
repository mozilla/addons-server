from decimal import Decimal
import json

import mock
from nose import SkipTest
from nose.tools import eq_

import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from lib.crypto.webpay import sign_webpay_jwt
from mkt.purchase.tests.samples import refund
from stats.models import Contribution
from users.models import UserProfile


class SalesTest(object):

    def setUp(self):
        self.app = Addon.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=999)
        self.sale = Contribution.objects.create(
                            addon=self.app, amount=Decimal(1),
                            uuid='sample:uuid',
                            type=amo.CONTRIB_PURCHASE, user=self.user)


class TestPostback(SalesTest, amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube', 'base/users']

    def setUp(self):
        raise SkipTest
        super(TestPostback, self).setUp()
        self.url = reverse('webpay.postback')

    @mock.patch('lib.crypto.webpay.verify_webpay_jwt')
    def test_not_valid(self, verify_webpay_jwt):
        verify_webpay_jwt.return_value = {'valid': False}
        eq_(self.client.post(self.url).status_code, 400)

    @mock.patch('mkt.purchase.webpay.parse_from_webpay')
    def test_wrong_uid(self, parse_from_webpay):
        parse_from_webpay.return_value = {'response':
                                            {'transactionID': '4'}}
        eq_(self.client.post(self.url).status_code, 400)

    @mock.patch('mkt.purchase.webpay.parse_from_webpay')
    def test_parsed(self, parse_from_webpay):
        parse_from_webpay.return_value = {'response':
                                            {'transactionID': '1'}}
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.sale.is_refunded(), True)

        refunds = Contribution.objects.filter(type=amo.CONTRIB_REFUND)
        eq_(len(refunds), 1)

        refund = refunds[0]
        eq_(refund.amount, -self.sale.amount)
        eq_(refund.related, self.sale)

    @mock.patch('mkt.purchase.webpay.parse_from_webpay')
    def test_purchased(self, parse_from_webpay):
        # Just a double check that receipts will be invalid.
        parse_from_webpay.return_value = {'response':
                                            {'transactionID': '1'}}

        eq_(self.app.has_purchased(self.user), True)
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.app.has_purchased(self.user), False)
        eq_(self.app.is_refunded(self.user), True)

    def test_encode(self):
        data = sign_webpay_jwt(refund)
        res = self.client.post(self.url, data, content_type='application/json')
        eq_(res.status_code, 200)
        eq_(self.sale.is_refunded(), True)

    @mock.patch('mkt.purchase.webpay_tasks._notify')
    def test_notifies(self, _notify):
        data = sign_webpay_jwt(refund)
        res = self.client.post(self.url, data, content_type='application/json')
        eq_(res.status_code, 200)
        assert _notify.called
