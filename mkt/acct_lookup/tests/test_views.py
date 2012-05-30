from decimal import Decimal
import json

from nose.tools import eq_

from addons.models import Addon
import amo
from amo.urlresolvers import reverse
from amo.tests import TestCase, ESTestCase, app_factory
from market.models import Refund
from stats.models import Contribution
from users.cron import reindex_users
from users.models import UserProfile


class AcctLookupTest:

    def setUp(self):
        assert self.client.login(username='support-staff@mozilla.com',
                                 password='password')


class TestAcctSummary(AcctLookupTest, TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestAcctSummary, self).setUp()
        self.user_id = 31337  # steamcube
        self.steamcube = Addon.objects.get(pk=337141)
        self.otherapp = app_factory(app_slug='otherapp')
        self.reg_user = UserProfile.objects.get(email='regular@mozilla.com')
        self.summary_url = reverse('acct_lookup.summary', args=[self.user_id])

    def buy_stuff(self, contrib_type):
        for i in range(3):
            if i == 1:
                curr = 'GBR'
            else:
                curr = 'USD'
            amount = Decimal('2.00')
            Contribution.objects.create(addon=self.steamcube,
                                        type=contrib_type,
                                        currency=curr,
                                        amount=amount,
                                        user_id=self.user_id)

    def summary(self, expected_status=200):
        res = self.client.get(self.summary_url)
        eq_(res.status_code, expected_status)
        return res

    def test_home_auth(self):
        self.client.logout()
        res = self.client.get(reverse('acct_lookup.home'))
        self.assertLoginRedirects(res, reverse('acct_lookup.home'))

    def test_summary_auth(self):
        self.client.logout()
        res = self.client.get(self.summary_url)
        self.assertLoginRedirects(res, self.summary_url)

    def test_home(self):
        res = self.client.get(reverse('acct_lookup.home'))
        self.assertNoFormErrors(res)
        eq_(res.status_code, 200)

    def test_basic_summary(self):
        res = self.summary()
        eq_(res.context['account'].pk, self.user_id)

    def test_app_counts(self):
        self.buy_stuff(amo.CONTRIB_PURCHASE)
        sm = self.summary().context['app_summary']
        eq_(sm['app_total'], 3)
        eq_(sm['app_amount']['USD'], 4.0)
        eq_(sm['app_amount']['GBR'], 2.0)

    def test_inapp_counts(self):
        self.buy_stuff(amo.CONTRIB_INAPP)
        sm = self.summary().context['app_summary']
        eq_(sm['inapp_total'], 3)
        eq_(sm['inapp_amount']['USD'], 4.0)
        eq_(sm['inapp_amount']['GBR'], 2.0)

    def test_requested_refunds(self):
        contrib = Contribution.objects.create(type=amo.CONTRIB_PURCHASE,
                                              user_id=self.user_id,
                                              addon=self.steamcube,
                                              currency='USD',
                                              amount='0.99')
        Refund.objects.create(contribution=contrib)
        res = self.summary()
        eq_(res.context['refund_summary']['requested'], 1)
        eq_(res.context['refund_summary']['approved'], 0)

    def test_approved_refunds(self):
        contrib = Contribution.objects.create(type=amo.CONTRIB_PURCHASE,
                                              user_id=self.user_id,
                                              addon=self.steamcube,
                                              currency='USD',
                                              amount='0.99')
        Refund.objects.create(contribution=contrib,
                              status=amo.REFUND_APPROVED_INSTANT)
        res = self.summary()
        eq_(res.context['refund_summary']['requested'], 1)
        eq_(res.context['refund_summary']['approved'], 1)

    def test_app_created(self):
        res = self.summary()
        eq_(len(res.context['user_addons']), 1)


class TestAcctSearch(AcctLookupTest, ESTestCase):
    fixtures = ['base/users']

    @classmethod
    def setUpClass(cls):
        super(TestAcctSearch, cls).setUpClass()
        reindex_users()

    def setUp(self):
        super(TestAcctSearch, self).setUp()
        self.user = UserProfile.objects.get(username='clouserw')

    def search(self, q, expect_results=True):
        res = self.client.get(reverse('acct_lookup.search'), {'q': q})
        data = json.loads(res.content)
        if expect_results:
            assert len(data['results']), 'should be more than 0 results'
        return data

    def verify_result(self, data):
        eq_(data['results'][0]['username'], self.user.username)
        eq_(data['results'][0]['display_name'], self.user.display_name)
        eq_(data['results'][0]['email'], self.user.email)
        eq_(data['results'][0]['id'], self.user.pk)
        eq_(data['results'][0]['url'], reverse('acct_lookup.summary',
                                               args=[self.user.pk]))

    def test_auth_required(self):
        self.client.logout()
        res = self.client.get(reverse('acct_lookup.search'))
        self.assertLoginRedirects(res, reverse('acct_lookup.search'))

    def test_by_username(self):
        self.user.update(username='newusername')
        self.refresh()
        data = self.search('newus')
        self.verify_result(data)

    def test_by_display_name(self):
        self.user.update(display_name='Kumar McMillan')
        self.refresh()
        data = self.search('mcmill')
        self.verify_result(data)

    def test_by_id(self):
        data = self.search(self.user.pk)
        self.verify_result(data)

    def test_by_email(self):
        self.user.update(email='fonzi@happydays.com')
        self.refresh()
        data = self.search('fonzih')
        self.verify_result(data)

    def test_no_results(self):
        data = self.search('__garbage__', expect_results=False)
        eq_(data['results'], [])
