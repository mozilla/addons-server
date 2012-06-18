from mock import Mock, patch
from nose.tools import eq_
import waffle

from addons.models import Addon
import amo
import amo.tests
from amo.helpers import urlparams
from amo.urlresolvers import reverse
from market.models import AddonPremium
from paypal.tests.test_views import sample_purchase
from stats.models import Contribution
from users.models import UserProfile


uuid = '123'
sample_ipn = sample_purchase.copy()
sample_ipn['tracking_id'] = uuid


class TestPurchaseIPNOrder(amo.tests.TestCase):
    # Specific tests that cross a few boundaries of purchase and
    # IPN processing to make sure that a few of the more complicated
    # scenarios don't break things.
    fixtures = ['base/apps', 'base/addon_592', 'base/users', 'market/prices']

    def setUp(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        self.addon = Addon.objects.get(pk=592)
        self.addon.update(premium_type=amo.ADDON_PREMIUM,
                          status=amo.STATUS_PUBLIC)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.finished = urlparams(reverse('addons.purchase.finished',
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
        return (con.uuid == None
                and con.transaction_id == uuid
                and con.post_data)

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
