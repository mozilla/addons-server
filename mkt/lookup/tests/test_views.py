from datetime import datetime, timedelta
from decimal import Decimal
import json

from pyquery import PyQuery as pq
from nose.exc import SkipTest
from nose.tools import eq_

import amo
from abuse.models import AbuseReport
from addons.cron import reindex_addons
from addons.models import Addon, AddonUser
from amo.helpers import urlparams
from amo.tests import addon_factory, app_factory, ESTestCase, TestCase
from amo.urlresolvers import reverse
from devhub.models import ActivityLog
from market.models import AddonPaymentData, AddonPremium, Price, Refund
from mkt.webapps.models import Installed, Webapp
from stats.models import Contribution, DownloadCount
from users.cron import reindex_users
from users.models import UserProfile


class TestAcctSummary(TestCase):
    fixtures = ['base/users', 'base/addon_3615',
                'webapps/337141-steamcube']

    def setUp(self):
        super(TestAcctSummary, self).setUp()
        self.user = UserProfile.objects.get(pk=31337)  # steamcube
        self.steamcube = Addon.objects.get(pk=337141)
        self.otherapp = app_factory(app_slug='otherapp')
        self.reg_user = UserProfile.objects.get(email='regular@mozilla.com')
        self.summary_url = reverse('lookup.user_summary',
                                   args=[self.user.pk])
        assert self.client.login(username='support-staff@mozilla.com',
                                 password='password')

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
                                        user_id=self.user.pk)

    def summary(self, expected_status=200):
        res = self.client.get(self.summary_url)
        eq_(res.status_code, expected_status)
        return res

    def payment_data(self):
        return {'full_name': 'Ed Peabody Jr.',
                'business_name': 'Mr. Peabody',
                'phone': '(1) 773-111-2222',
                'address_one': '1111 W Leland Ave',
                'address_two': 'Apt 1W',
                'city': 'Chicago',
                'post_code': '60640',
                'country': 'USA',
                'state': 'Illinois'}

    def test_home_auth(self):
        self.client.logout()
        res = self.client.get(reverse('lookup.home'))
        self.assertLoginRedirects(res, reverse('lookup.home'))

    def test_summary_auth(self):
        self.client.logout()
        res = self.client.get(self.summary_url)
        self.assertLoginRedirects(res, self.summary_url)

    def test_home(self):
        res = self.client.get(reverse('lookup.home'))
        self.assertNoFormErrors(res)
        eq_(res.status_code, 200)

    def test_basic_summary(self):
        res = self.summary()
        eq_(res.context['account'].pk, self.user.pk)

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
                                              user_id=self.user.pk,
                                              addon=self.steamcube,
                                              currency='USD',
                                              amount='0.99')
        Refund.objects.create(contribution=contrib)
        res = self.summary()
        eq_(res.context['refund_summary']['requested'], 1)
        eq_(res.context['refund_summary']['approved'], 0)

    def test_approved_refunds(self):
        contrib = Contribution.objects.create(type=amo.CONTRIB_PURCHASE,
                                              user_id=self.user.pk,
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
        # Number of apps/add-ons belonging to this user.
        eq_(len(res.context['user_addons']), 1)

    def test_paypal_ids(self):
        self.user.addons.update(paypal_id='somedev@app.com')
        res = self.summary()
        eq_(list(res.context['paypal_ids']), [u'somedev@app.com'])

    def test_no_paypal(self):
        self.user.addons.update(paypal_id='')
        res = self.summary()
        eq_(list(res.context['paypal_ids']), [])

    def test_payment_data(self):
        payment_data = self.payment_data()
        AddonPaymentData.objects.create(addon=self.steamcube,
                                        **payment_data)
        res = self.summary()
        pd = res.context['payment_data'][0]
        for key, value in payment_data.iteritems():
            eq_(pd[key], value)

    def test_no_payment_data(self):
        res = self.summary()
        eq_(len(res.context['payment_data']), 0)

    def test_no_duplicate_payment_data(self):
        role = AddonUser.objects.create(user=self.user,
                                        addon=self.otherapp,
                                        role=amo.AUTHOR_ROLE_DEV)
        self.otherapp.addonuser_set.add(role)
        payment_data = self.payment_data()
        AddonPaymentData.objects.create(addon=self.steamcube,
                                        **payment_data)
        AddonPaymentData.objects.create(addon=self.otherapp,
                                        **payment_data)
        res = self.summary()
        eq_(len(res.context['payment_data']), 1)
        pd = res.context['payment_data'][0]
        for key, value in payment_data.iteritems():
            eq_(pd[key], value)


class SearchTestMixin(object):

    def search(self, expect_results=True, **data):
        res = self.client.get(self.url, data)
        data = json.loads(res.content)
        if expect_results:
            assert len(data['results']), 'should be more than 0 results'
        return data

    def test_auth_required(self):
        self.client.logout()
        res = self.client.get(self.url)
        self.assertLoginRedirects(res, self.url)

    def test_no_results(self):
        data = self.search(q='__garbage__', expect_results=False)
        eq_(data['results'], [])


class TestAcctSearch(ESTestCase, SearchTestMixin):
    fixtures = ['base/users']

    @classmethod
    def setUpClass(cls):
        super(TestAcctSearch, cls).setUpClass()
        reindex_users()

    def setUp(self):
        super(TestAcctSearch, self).setUp()
        self.url = reverse('lookup.user_search')
        self.user = UserProfile.objects.get(username='clouserw')
        assert self.client.login(username='support-staff@mozilla.com',
                                 password='password')

    def verify_result(self, data):
        eq_(data['results'][0]['name'], self.user.username)
        eq_(data['results'][0]['display_name'], self.user.display_name)
        eq_(data['results'][0]['email'], self.user.email)
        eq_(data['results'][0]['id'], self.user.pk)
        eq_(data['results'][0]['url'], reverse('lookup.user_summary',
                                               args=[self.user.pk]))

    def test_by_username(self):
        self.user.update(username='newusername')
        self.refresh()
        data = self.search(q='newus')
        self.verify_result(data)

    def test_by_username_with_dashes(self):
        self.user.update(username='kr-raj')
        self.refresh()
        data = self.search(q='kr-raj')
        self.verify_result(data)

    def test_by_display_name(self):
        self.user.update(display_name='Kumar McMillan')
        self.refresh()
        data = self.search(q='mcmill')
        self.verify_result(data)

    def test_by_id(self):
        data = self.search(q=self.user.pk)
        self.verify_result(data)

    def test_by_email(self):
        self.user.update(email='fonzi@happydays.com')
        self.refresh()
        data = self.search(q='fonzih')
        self.verify_result(data)


class TestAppSearch(ESTestCase, SearchTestMixin):
    fixtures = ['base/users', 'webapps/337141-steamcube',
                'base/addon_3615']

    @classmethod
    def setUpClass(cls):
        super(TestAppSearch, cls).setUpClass()
        reindex_addons()

    def setUp(self):
        super(TestAppSearch, self).setUp()
        self.url = reverse('lookup.app_search')
        self.app = Addon.objects.get(pk=337141)
        assert self.client.login(username='support-staff@mozilla.com',
                                 password='password')

    def verify_result(self, data):
        eq_(data['results'][0]['name'], self.app.name.localized_string)
        eq_(data['results'][0]['id'], self.app.pk)
        eq_(data['results'][0]['url'], reverse('lookup.app_summary',
                                               args=[self.app.pk]))

    def test_by_name_part(self):
        self.app.name = 'This is Steamcube'
        self.app.save()
        self.refresh()
        data = self.search(q='steamcube')
        self.verify_result(data)

    def test_multiword(self):
        self.app.name = 'Firefox Marketplace'
        self.app.save()
        self.refresh()
        data = self.search(q='Firefox Marketplace')
        self.verify_result(data)

    def test_by_stem_name(self):
        self.app.name = 'Instigation'
        self.app.save()
        self.refresh()
        data = self.search(q='instigate')
        self.verify_result(data)

    def test_by_guid(self):
        self.app = Addon.objects.get(pk=3615)
        assert self.app.guid, 'Expected this addon to have a guid'
        self.app = Addon.objects.get(guid=self.app.guid)
        data = self.search(q=self.app.guid, type=amo.ADDON_EXTENSION)
        self.verify_result(data)

    def test_by_random_guid(self):
        self.app = Addon.objects.get(pk=3615)
        self.app.update(guid='__bonanza__')
        data = self.search(q=self.app.guid, type=amo.ADDON_EXTENSION)
        self.verify_result(data)

    def test_by_id(self):
        data = self.search(q=self.app.pk)
        self.verify_result(data)


class AppSummaryTest(TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube',
                'base/addon_3615', 'market/prices']

    def _setUp(self):
        self.app = Addon.objects.get(pk=337141)
        self.url = reverse('lookup.app_summary',
                           args=[self.app.pk])
        assert self.client.login(username='support-staff@mozilla.com',
                                 password='password')

    def summary(self, expected_status=200):
        res = self.client.get(self.url)
        eq_(res.status_code, expected_status)
        return res


class TestAppSummary(AppSummaryTest):

    def setUp(self):
        super(TestAppSummary, self).setUp()
        self._setUp()

    def test_search_matches_type(self):
        res = self.summary()
        eq_(pq(res.content)('#app-search-form select option[selected]').val(),
            str(amo.ADDON_WEBAPP))

    def test_authors(self):
        user = UserProfile.objects.get(username='admin')
        role = AddonUser.objects.create(user=user,
                                        addon=self.app,
                                        role=amo.AUTHOR_ROLE_DEV)
        self.app.addonuser_set.add(role)
        res = self.summary()
        eq_(res.context['authors'][0].display_name,
            user.display_name)

    def test_visible_authors(self):
        for role in (amo.AUTHOR_ROLE_DEV,
                     amo.AUTHOR_ROLE_OWNER,
                     amo.AUTHOR_ROLE_VIEWER,
                     amo.AUTHOR_ROLE_SUPPORT):
            user = UserProfile.objects.create(username=role)
            role = AddonUser.objects.create(user=user,
                                            addon=self.app,
                                            role=role)
            self.app.addonuser_set.add(role)
        res = self.summary()

        eq_(sorted([u.username for u in res.context['authors']]),
            [str(amo.AUTHOR_ROLE_DEV), str(amo.AUTHOR_ROLE_OWNER)])

    def test_details(self):
        res = self.summary()
        eq_(res.context['app'].manifest_url, self.app.manifest_url)
        eq_(res.context['app'].premium_type, amo.ADDON_FREE)
        eq_(res.context['price'], None)

    def test_price(self):
        price = Price.objects.get(pk=1)
        AddonPremium.objects.create(addon=self.app,
                                    price=price)
        res = self.summary()
        eq_(res.context['price'], price)

    def test_abuse_reports(self):
        for i in range(2):
            AbuseReport.objects.create(addon=self.app,
                                       ip_address='10.0.0.1',
                                       message='spam and porn everywhere')
        res = self.summary()
        eq_(res.context['abuse_reports'], 2)

    def test_permissions(self):
        raise SkipTest('we do not support permissions yet')


class DownloadSummaryTest(AppSummaryTest):

    def setUp(self):
        super(DownloadSummaryTest, self).setUp()
        self._setUp()
        self.users = [UserProfile.objects.get(pk=999),
                      UserProfile.objects.get(username='admin')]


class TestAppDownloadSummary(DownloadSummaryTest, TestCase):

    def setUp(self):
        super(TestAppDownloadSummary, self).setUp()
        self.addon = Addon.objects.get(pk=3615)

    def test_7_days(self):
        for user in self.users:
            Installed.objects.create(addon=self.app, user=user)
        res = self.summary()
        eq_(res.context['downloads']['last_7_days'], 2)

    def test_ignore_older_than_7_days(self):
        _8_days_ago = datetime.now() - timedelta(days=8)
        for user in self.users:
            c = Installed.objects.create(addon=self.app, user=user)
            c.update(created=_8_days_ago)
        res = self.summary()
        eq_(res.context['downloads']['last_7_days'], 0)

    def test_24_hours(self):
        for user in self.users:
            Installed.objects.create(addon=self.app, user=user)
        res = self.summary()
        eq_(res.context['downloads']['last_24_hours'], 2)

    def test_ignore_older_than_24_hours(self):
        _25_hr_ago = datetime.now() - timedelta(hours=25)
        for user in self.users:
            c = Installed.objects.create(addon=self.app, user=user)
            c.update(created=_25_hr_ago)
        res = self.summary()
        eq_(res.context['downloads']['last_24_hours'], 0)

    def test_alltime_dl(self):
        for user in self.users:
            Installed.objects.create(addon=self.app, user=user)
        # Downloads for some other app that shouldn't be counted.
        for user in self.users:
            Installed.objects.create(addon=self.addon, user=user)
        res = self.summary()
        eq_(res.context['downloads']['alltime'], 2)


class TestAppSummaryPurchases(AppSummaryTest):

    def setUp(self):
        super(TestAppSummaryPurchases, self).setUp()
        self._setUp()

    def assert_totals(self, data):
        eq_(data['total'], 6)
        eq_(sorted(data['amounts']), [u'$6.00', u'\u20ac3.00'])

    def assert_empty(self, data):
        eq_(data['total'], 0)
        eq_(sorted(data['amounts']), [])

    def purchase(self, created=None, typ=amo.CONTRIB_PURCHASE):
        for curr, amount in (('USD', '2.00'), ('EUR', '1.00')):
            for i in range(3):
                c = Contribution.objects.create(addon=self.app,
                                                amount=Decimal(amount),
                                                currency=curr,
                                                type=typ)
                if created:
                    c.update(created=created)

    def test_24_hr(self):
        self.purchase()
        res = self.summary()
        self.assert_totals(res.context['purchases']['last_24_hours'])

    def test_ignore_older_than_24_hr(self):
        self.purchase(created=datetime.now() - timedelta(days=1,
                                                         minutes=1))
        res = self.summary()
        self.assert_empty(res.context['purchases']['last_24_hours'])

    def test_7_days(self):
        self.purchase(created=datetime.now() - timedelta(days=6,
                                                         minutes=55))
        res = self.summary()
        self.assert_totals(res.context['purchases']['last_7_days'])

    def test_ignore_older_than_7_days(self):
        self.purchase(created=datetime.now() - timedelta(days=7,
                                                         minutes=1))
        res = self.summary()
        self.assert_empty(res.context['purchases']['last_7_days'])

    def test_alltime(self):
        self.purchase(created=datetime.now() - timedelta(days=31))
        res = self.summary()
        self.assert_totals(res.context['purchases']['alltime'])

    def test_ignore_non_purchases(self):
        for typ in [amo.CONTRIB_REFUND,
                    amo.CONTRIB_CHARGEBACK,
                    amo.CONTRIB_PENDING,
                    amo.CONTRIB_INAPP_PENDING]:
            self.purchase(typ=typ)
        res = self.summary()
        self.assert_empty(res.context['purchases']['alltime'])

    def test_pay_methods(self):
        for paykey in ('AP-1234',  # indicates PayPal
                       'AP-1235',
                       None):  # indicates other
            Contribution.objects.create(addon=self.app,
                                        amount=Decimal('0.99'),
                                        currency='USD',
                                        paykey=paykey,
                                        type=amo.CONTRIB_PURCHASE)
        res = self.summary()
        eq_(sorted(res.context['payment_methods']),
            [u'33.3% of purchases via Other',
             u'66.7% of purchases via PayPal'])

    def test_inapp_pay_methods(self):
        Contribution.objects.create(addon=self.app,
                                    amount=Decimal('0.99'),
                                    currency='USD',
                                    paykey='AP-1235',
                                    type=amo.CONTRIB_INAPP)
        res = self.summary()
        eq_(res.context['payment_methods'],
            [u'100.0% of purchases via PayPal'])


class TestAppSummaryRefunds(AppSummaryTest):

    def setUp(self):
        super(TestAppSummaryRefunds, self).setUp()
        self._setUp()
        self.contrib1 = self.purchase()
        self.contrib2 = self.purchase()
        self.contrib3 = self.purchase()
        self.contrib4 = self.purchase()

    def purchase(self):
        return Contribution.objects.create(addon=self.app,
                                           amount=Decimal('0.99'),
                                           currency='USD',
                                           paykey='AP-1235',
                                           type=amo.CONTRIB_PURCHASE)

    def refund(self, refunds):
        for contrib, status in refunds:
            Refund.objects.create(contribution=contrib,
                                  status=status)

    def test_requested(self):
        self.refund(((self.contrib1, amo.REFUND_APPROVED),
                     (self.contrib2, amo.REFUND_APPROVED),
                     (self.contrib3, amo.REFUND_DECLINED),
                     (self.contrib4, amo.REFUND_DECLINED)))
        res = self.summary()
        eq_(res.context['refunds']['requested'], 2)
        eq_(res.context['refunds']['percent_of_purchases'], '50.0%')

    def test_no_refunds(self):
        res = self.summary()
        eq_(res.context['refunds']['requested'], 0)
        eq_(res.context['refunds']['percent_of_purchases'], '0.0%')
        eq_(res.context['refunds']['auto-approved'], 0)
        eq_(res.context['refunds']['approved'], 0)
        eq_(res.context['refunds']['rejected'], 0)

    def test_auto_approved(self):
        self.refund(((self.contrib1, amo.REFUND_APPROVED),
                     (self.contrib2, amo.REFUND_APPROVED_INSTANT)))
        res = self.summary()
        eq_(res.context['refunds']['auto-approved'], 1)

    def test_approved(self):
        self.refund(((self.contrib1, amo.REFUND_APPROVED),
                     (self.contrib2, amo.REFUND_DECLINED)))
        res = self.summary()
        eq_(res.context['refunds']['approved'], 1)

    def test_rejected(self):
        self.refund(((self.contrib1, amo.REFUND_APPROVED),
                     (self.contrib2, amo.REFUND_DECLINED),
                     (self.contrib3, amo.REFUND_FAILED)))
        res = self.summary()
        eq_(res.context['refunds']['rejected'], 2)


class TestAddonDownloadSummary(DownloadSummaryTest, TestCase):

    def setUp(self):
        super(TestAddonDownloadSummary, self).setUp()
        self.app = Addon.objects.get(pk=3615)
        self.url = reverse('lookup.app_summary',
                           args=[self.app.pk])

    def test_7_days(self):
        for user in self.users:
            DownloadCount.objects.create(addon=self.app, count=2,
                                         date=datetime.now().date())
        res = self.summary()
        eq_(res.context['downloads']['last_7_days'], 4)

    def test_ignore_older_than_7_days(self):
        _8_days_ago = datetime.now() - timedelta(days=8)
        for user in self.users:
            c = DownloadCount.objects.create(addon=self.app, count=2,
                                             date=datetime.now().date())
            c.date = _8_days_ago.date()
            c.save()
        res = self.summary()
        eq_(res.context['downloads']['last_7_days'], 0)

    def test_24_hours(self):
        for user in self.users:
            DownloadCount.objects.create(addon=self.app, count=2,
                                         date=datetime.now().date())
        res = self.summary()
        eq_(res.context['downloads']['last_24_hours'], 4)

    def test_ignore_older_than_24_hours(self):
        yesterday = datetime.now().date() - timedelta(days=1)
        for user in self.users:
            c = DownloadCount.objects.create(addon=self.app, count=2,
                                             date=datetime.now().date())
            c.date = yesterday
            c.save()
        res = self.summary()
        eq_(res.context['downloads']['last_24_hours'], 0)

    def test_alltime_dl(self):
        for i in range(2):
            DownloadCount.objects.create(addon=self.app, count=2,
                                         date=datetime.now().date())
        # Downloads for some other addon that shouldn't be counted.
        addon = addon_factory()
        for user in self.users:
            DownloadCount.objects.create(addon=addon, count=2,
                                         date=datetime.now().date())
        res = self.summary()
        eq_(res.context['downloads']['alltime'], 4)

    def test_zero_alltime_dl(self):
        # Downloads for some other addon that shouldn't be counted.
        addon = addon_factory()
        for user in self.users:
            DownloadCount.objects.create(addon=addon, count=2,
                                         date=datetime.now().date())
        res = self.summary()
        eq_(res.context['downloads']['alltime'], 0)


class TestPurchases(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.reviewer = UserProfile.objects.get(username='admin')
        self.user = UserProfile.objects.get(pk=999)
        self.url = reverse('lookup.user_purchases', args=[self.user.pk])

    def test_not_allowed(self):
        self.client.logout()
        self.assertLoginRequired(self.client.get(self.url))

    def test_not_even_mine(self):
        self.client.login(username=self.user.email, password='password')
        eq_(self.client.get(self.url).status_code, 403)

    def test_access(self):
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(len(pq(res.content)('p.no-results')), 1)

    def test_purchase_shows_up(self):
        Contribution.objects.create(user=self.user, addon=self.app,
                                    amount=1, type=amo.CONTRIB_PURCHASE)
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('ol.listing a.mkt-tile').attr('href'),
            urlparams(self.app.get_detail_url(), src=''))

    def test_no_support_link(self):
        for type_ in [amo.CONTRIB_PURCHASE, amo.CONTRIB_INAPP]:
            Contribution.objects.create(user=self.user, addon=self.app,
                                        amount=1, type=type_)
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(len(doc('.item a.request-support')), 0)


class TestActivity(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.reviewer = UserProfile.objects.get(username='admin')
        self.user = UserProfile.objects.get(pk=999)
        self.url = reverse('lookup.user_activity', args=[self.user.pk])

    def test_not_allowed(self):
        self.client.logout()
        self.assertLoginRequired(self.client.get(self.url))

    def test_not_even_mine(self):
        self.client.login(username=self.user.email, password='password')
        eq_(self.client.get(self.url).status_code, 403)

    def test_access(self):
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(len(pq(res.content)('.simple-log div')), 0)

    def test_log(self):
        self.client.login(username=self.reviewer.email, password='password')
        self.client.get(self.url)
        log_item = ActivityLog.objects.get(action=amo.LOG.ADMIN_VIEWED_LOG.id)
        eq_(len(log_item.arguments), 1)
        eq_(log_item.arguments[0].id, self.reviewer.id)
        eq_(log_item.user, self.user)

    def test_display(self):
        amo.log(amo.LOG.PURCHASE_ADDON, self.app, user=self.user)
        amo.log(amo.LOG.ADMIN_USER_EDITED, self.user, 'spite', user=self.user)
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        assert 'purchased' in doc('li.item').eq(0).text()
        assert 'edited' in doc('li.item').eq(1).text()
