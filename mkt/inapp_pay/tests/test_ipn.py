import fudge
from mock import patch, Mock
from nose import SkipTest
from nose.tools import eq_
import waffle

from django.conf import settings

from addons.models import Addon
import amo
from mkt.inapp_pay.models import InappConfig
from mkt.inapp_pay.tests.test_views import InappPaymentUtil
from paypal.tests.test_views import (PaypalTest, sample_reversal,
                                     sample_chained_refund)
from users.models import UserProfile


@patch('paypal.views.requests.post')
@patch.object(settings, 'DEBUG', True)
class TestInappIPN(InappPaymentUtil, PaypalTest):
    fixtures = ['webapps/337141-steamcube', 'base/users', 'market/prices']

    @patch.object(settings, 'DEBUG', True)
    def setUp(self):
        raise SkipTest
        super(TestInappIPN, self).setUp()
        self.app = self.get_app()
        cfg = self.inapp_config = InappConfig(addon=self.app,
                                              status=amo.INAPP_STATUS_ACTIVE)
        cfg.public_key = self.app_id = InappConfig.generate_public_key()
        cfg.private_key = self.app_secret = InappConfig.generate_private_key()
        cfg.save()
        self.app.paypal_id = 'app-dev-paypal@theapp.com'
        self.app.save()

        waffle.models.Switch.objects.create(name='in-app-payments-ui',
                                            active=True)
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def get_app(self):
        return Addon.objects.get(pk=337141)

    @fudge.patch('mkt.inapp_pay.tasks.chargeback_notify')
    def test_reversal(self, post, chargeback_notify):
        post.return_value = Mock(text='VERIFIED')
        con = self.make_contrib(transaction_id=sample_reversal['tracking_id'])
        pay = self.make_payment(contrib=con)

        chargeback_notify.expects('delay').with_args(pay.pk, 'reversal')

        ipn = sample_reversal.copy()
        response = self.client.post(self.url, ipn)
        eq_(response.content.strip(), 'Success!')
        eq_(response.status_code, 200)

    @fudge.patch('mkt.inapp_pay.tasks.chargeback_notify')
    def test_refund(self, post, chargeback_notify):
        post.return_value = Mock(text='VERIFIED')
        tx = sample_chained_refund['tracking_id']
        con = self.make_contrib(transaction_id=tx)
        pay = self.make_payment(contrib=con)

        chargeback_notify.expects('delay').with_args(pay.pk, 'refund')

        ipn = sample_chained_refund.copy()
        response = self.client.post(self.url, ipn)
        eq_(response.content.strip(), 'Success!')
        eq_(response.status_code, 200)

    def test_completion(self, post):
        # TODO(Kumar) trigger notify hook from IPN
        post.return_value = Mock(text='VERIFIED')
