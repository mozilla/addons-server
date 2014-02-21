from mock import Mock, patch
from nose import SkipTest
from nose.tools import eq_

from addons.models import Addon
import amo
import amo.tests
from amo.helpers import urlparams
from amo.urlresolvers import reverse
from market.models import AddonPremium
from stats.models import Contribution
from users.models import UserProfile


uuid = '123'

sample_purchase = {
    'action_type': 'PAY',
    'cancel_url': 'http://some.url/cancel',
    'charset': 'windows-1252',
    'fees_payer': 'EACHRECEIVER',
    'ipn_notification_url': 'http://some.url.ipn',
    'log_default_shipping_address_in_transaction': 'false',
    'memo': 'Purchase of Sinuous',
    'notify_version': 'UNVERSIONED',
    'pay_key': '1234',
    'payment_request_date': 'Mon Nov 21 22:30:48 PST 2011',
    'return_url': 'http://some.url/return',
    'reverse_all_parallel_payments_on_error': 'false',
    'sender_email': 'some.other@gmail.com',
    'status': 'COMPLETED',
    'test_ipn': '1',
    'tracking_id': '5678',
    'transaction[0].amount': 'USD 0.01',
    'transaction[0].id': 'ABC',
    'transaction[0].id_for_sender_txn': 'DEF',
    'transaction[0].is_primary_receiver': 'false',
    'transaction[0].paymentType': 'DIGITALGOODS',
    'transaction[0].pending_reason': 'NONE',
    'transaction[0].receiver': 'some@gmail.com',
    'transaction[0].status': 'Completed',
    'transaction[0].status_for_sender_txn': 'Completed',
    'transaction_type': 'Adaptive Payment PAY',
    'verify_sign': 'zyx'
}

sample_ipn = sample_purchase.copy()
sample_ipn['tracking_id'] = uuid


class TestPurchaseIPNOrder(amo.tests.TestCase):
    # Specific tests that cross a few boundaries of purchase and
    # IPN processing to make sure that a few of the more complicated
    # scenarios don't break things.
    fixtures = ['base/apps', 'base/addon_592', 'base/users', 'market/prices']

    def setUp(self):
        raise SkipTest

        self.addon = Addon.objects.get(pk=592)
        self.addon.update(premium_type=amo.ADDON_PREMIUM,
                          status=amo.STATUS_PUBLIC)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.finished = urlparams(reverse('addons.paypal.finished',
                                          args=[self.addon.slug, 'complete']),
                             uuid=uuid)
        self.ipn = reverse('amo.paypal')
        self.client.login(username='regular@mozilla.com', password='password')

        AddonPremium.objects.create(addon=self.addon, price_id=1)
        self.con = Contribution.objects.create(addon=self.addon, uuid=uuid,
                                               user=self.user, paykey='sdf',
                                               type=amo.CONTRIB_PENDING)

    def get_contribution(self):
        return Contribution.objects.get(pk=self.con.pk)

    def is_contribution_good(self):
        # Checks that the IPN has been by and its all good.
        con = self.get_contribution()
        return (con.uuid is None and con.transaction_id == uuid and
                con.post_data)

    def urlopener(self, status):
        # Pretend to be requests or ullib2. Hot.
        m = Mock()
        m.readline.return_value = status
        m.text = status
        return m

    @patch('paypal.check_purchase')
    def get_finished(self, check_purchase):
        check_purchase.return_value = 'COMPLETED'
        response = self.client.get(self.finished)
        eq_(response.status_code, 200)

    @patch('paypal.views.requests.post')
    def get_ipn(self, urlopen):
        urlopen.return_value = self.urlopener('VERIFIED')
        response = self.client.post(self.ipn, sample_ipn)
        eq_(response.status_code, 200)

    def test_result(self):
        self.get_finished()
        assert self.addon.has_purchased(self.user)
        assert not self.is_contribution_good()

    def test_result_then_ipn(self):
        self.get_finished()
        assert self.addon.has_purchased(self.user)
        assert not self.is_contribution_good()

        self.get_ipn()
        assert self.addon.has_purchased(self.user)
        assert self.is_contribution_good()

    def test_ipn_no_result(self):
        self.get_ipn()
        assert self.addon.has_purchased(self.user)
        assert self.is_contribution_good()

    def test_ipn_then_result(self):
        self.get_ipn()
        assert self.addon.has_purchased(self.user)
        assert self.is_contribution_good()

        self.get_finished()
        assert self.addon.has_purchased(self.user)
        assert self.is_contribution_good()
