import json
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.test.client import RequestFactory
from django.utils.encoding import smart_str

import mock
from babel import numbers
from curling.lib import HttpClientError
from nose.exc import SkipTest
from nose.tools import eq_, ok_
from pyquery import PyQuery as pq
from slumber import exceptions

import amo
import amo.tests
from abuse.models import AbuseReport
from addons.cron import reindex_addons
from addons.models import Addon, AddonUser
from amo.tests import (addon_factory, app_factory, ESTestCase,
                       req_factory_factory, TestCase)
from amo.urlresolvers import reverse
from devhub.models import ActivityLog
from market.models import AddonPaymentData, Refund
from stats.models import Contribution, DownloadCount
from users.cron import reindex_users
from users.models import Group, GroupUser, UserProfile

from mkt.constants.payments import COMPLETED, FAILED, PENDING, REFUND_STATUSES
from mkt.developers.tests.test_views_payments import (setup_payment_account,
                                                      TEST_PACKAGE_ID)
from mkt.lookup.views import (_transaction_summary, transaction_refund,
                              user_delete, user_summary)
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp


@mock.patch.object(settings, 'TASK_USER_ID', 999)
class TestAcctSummary(TestCase):
    fixtures = fixture('user_support_staff', 'user_999', 'webapp_337141',
                       'user_operator')

    def setUp(self):
        super(TestAcctSummary, self).setUp()
        self.user = UserProfile.objects.get(username='31337')  # steamcube
        self.steamcube = Addon.objects.get(pk=337141)
        self.otherapp = app_factory(app_slug='otherapp')
        self.reg_user = UserProfile.objects.get(email='regular@mozilla.com')
        self.summary_url = reverse('lookup.user_summary', args=[self.user.pk])
        self.login(UserProfile.objects.get(username='support_staff'))

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

    def test_requested_refunds(self):
        contrib = Contribution.objects.create(type=amo.CONTRIB_PURCHASE,
                                              user_id=self.user.pk,
                                              addon=self.steamcube,
                                              currency='USD',
                                              amount='0.99')
        Refund.objects.create(contribution=contrib, user=self.user)
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
                              status=amo.REFUND_APPROVED_INSTANT,
                              user=self.user)
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

    def test_operator_app_lookup_only(self):
        GroupUser.objects.create(
            group=Group.objects.get(name='Operators'),
            user=UserProfile.objects.get(username='support_staff'))
        res = self.client.get(reverse('lookup.home'))
        doc = pq(res.content)
        eq_(doc('#app-search-form select').length, 0)

    def test_delete_user(self):
        staff = UserProfile.objects.get(username='support_staff')
        req = req_factory_factory(
            reverse('lookup.user_delete', args=[self.user.id]), user=staff,
            post=True, data={'delete_reason': 'basketball reasons'})

        r = user_delete(req, self.user.id)
        self.assert3xx(r, reverse('lookup.user_summary', args=[self.user.id]))

        # Test data.
        assert UserProfile.objects.get(id=self.user.id).deleted
        eq_(staff, ActivityLog.objects.for_user(self.user).filter(
            action=amo.LOG.DELETE_USER_LOOKUP.id)[0].user)

        # Test frontend.
        req = req_factory_factory(
            reverse('lookup.user_summary', args=[self.user.id]), user=staff)
        r = user_summary(req, self.user.id)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#delete-user dd:eq(1)').text(), 'basketball reasons')


class TestBangoRedirect(TestCase):
    fixtures = fixture('user_support_staff', 'user_999', 'webapp_337141',
                       'user_operator')

    def setUp(self):
        super(TestBangoRedirect, self).setUp()
        self.user = UserProfile.objects.get(username='31337')  # steamcube
        self.steamcube = Addon.objects.get(pk=337141)
        self.otherapp = app_factory(app_slug='otherapp')
        self.reg_user = UserProfile.objects.get(email='regular@mozilla.com')
        self.summary_url = reverse('lookup.user_summary', args=[self.user.pk])
        self.login(UserProfile.objects.get(username='support_staff'))
        self.create_switch('bango-portal')
        self.steamcube.update(premium_type=amo.ADDON_PREMIUM)
        self.account = setup_payment_account(self.steamcube, self.user)
        self.portal_url = reverse('lookup.bango_portal_from_package',
            args=[self.account.payment_account.account_id])
        self.authentication_token = u'D0A44686-D4A3-4B2F-9BEB-5E4975E35192'

    @mock.patch('mkt.developers.views_payments.client.api')
    def test_bango_portal_redirect(self, api):
        api.bango.login.post.return_value = {
            'person_id': 600925,
            'email_address': u'admin@place.com',
            'authentication_token': self.authentication_token,
        }
        res = self.client.get(self.portal_url)
        eq_(res.status_code, 302)
        eq_(api.bango.login.post.call_args[0][0]['packageId'],
            int(TEST_PACKAGE_ID))
        redirect_url = res['Location']
        assert self.authentication_token in redirect_url, redirect_url
        assert 'emailAddress=admin%40place.com' in redirect_url, redirect_url

    @mock.patch('mkt.developers.views_payments.client.api')
    def test_bango_portal_redirect_api_error(self, api):
        message = 'Something went wrong.'
        error = {'__all__': [message]}
        api.bango.login.post.side_effect = HttpClientError(content=error)
        res = self.client.get(self.portal_url, follow=True)
        eq_(res.redirect_chain, [('http://testserver/lookup/', 302)])
        ok_(message in [msg.message for msg in res.context['messages']][0])

    @mock.patch('mkt.developers.views_payments.client.api')
    def test_bango_portal_redirect_role_error(self, api):
        self.login(self.user)
        res = self.client.get(self.portal_url)
        eq_(res.status_code, 403)


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


class TestAcctSearch(ESTestCase, SearchTestMixin):
    fixtures = fixture('user_10482', 'user_support_staff', 'user_operator')

    @classmethod
    def setUpClass(cls):
        super(TestAcctSearch, cls).setUpClass()
        reindex_users()

    def setUp(self):
        super(TestAcctSearch, self).setUp()
        self.url = reverse('lookup.user_search')
        self.user = UserProfile.objects.get(username='clouserw')
        self.login(UserProfile.objects.get(username='support_staff'))

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

    @mock.patch('mkt.constants.lookup.SEARCH_LIMIT', 2)
    @mock.patch('mkt.constants.lookup.MAX_RESULTS', 3)
    def test_all_results(self):
        for x in range(4):
            name = 'chr' + str(x)
            UserProfile.objects.create(username=name, name=name,
                                       email=name + '@gmail.com')
        self.refresh()

        # Test not at search limit.
        data = self.search(q='clouserw')
        eq_(len(data['results']), 1)

        # Test search limit.
        data = self.search(q='chr')
        eq_(len(data['results']), 2)

        # Test maximum search result.
        data = self.search(q='chr', all_results=True)
        eq_(len(data['results']), 3)


class TestTransactionSearch(TestCase):
    fixtures = fixture('user_support_staff', 'user_999', 'user_operator')

    def setUp(self):
        self.uuid = 45
        self.url = reverse('lookup.transaction_search')
        self.client.login(username='support-staff@mozilla.com',
                          password='password')

    def test_redirect(self):
        r = self.client.get(self.url, {'q': self.uuid})
        self.assert3xx(r, reverse('lookup.transaction_summary',
                                  args=[self.uuid]))

    def test_no_perm(self):
        self.client.login(username='regular@mozilla.com',
                          password='password')
        r = self.client.get(self.url, {'q': self.uuid})
        eq_(r.status_code, 403)

        assert self.client.login(username='operator@mozilla.com',
                                 password='password')
        r = self.client.get(self.url, {'q': self.uuid})
        eq_(r.status_code, 403)


#@mock.patch.object(settings, 'TASK_USER_ID', 999)
class TestTransactionSummary(TestCase):
    fixtures = fixture('user_support_staff', 'user_999', 'user_operator')

    def setUp(self):
        self.uuid = 'some:uuid'
        self.transaction_id = 'some:tr'
        self.seller_uuid = 456
        self.related_tx_uuid = 789
        self.user = UserProfile.objects.get(pk=999)

        self.app = addon_factory(type=amo.ADDON_WEBAPP)
        self.contrib = Contribution.objects.create(
            addon=self.app, uuid=self.uuid, user=self.user,
            transaction_id=self.transaction_id)

        self.url = reverse('lookup.transaction_summary', args=[self.uuid])
        self.client.login(username='support-staff@mozilla.com',
                          password='password')

    @mock.patch.object(settings, 'TASK_USER_ID', 999)
    def create_test_refund(self):
        refund_contrib = Contribution.objects.create(
            addon=self.app, related=self.contrib, type=amo.CONTRIB_REFUND,
            transaction_id='testtransactionid', user=self.user)
        refund_contrib.enqueue_refund(amo.REFUND_PENDING, self.user)

    def test_transaction_summary(self):
        data = _transaction_summary(self.uuid)

        eq_(data['is_refundable'], False)
        eq_(data['contrib'].pk, self.contrib.pk)

    @mock.patch('mkt.lookup.views.client')
    def test_refund_status(self, solitude):
        solitude.api.bango.refund.status.get.return_value = {'status': PENDING}

        self.create_test_refund()
        data = _transaction_summary(self.uuid)

        eq_(data['refund_status'], REFUND_STATUSES[PENDING])

    @mock.patch('mkt.lookup.views.client')
    def test_is_refundable(self, solitude):
        solitude.api.bango.refund.status.get.return_value = {'status': PENDING}

        self.contrib.update(type=amo.CONTRIB_PURCHASE)
        data = _transaction_summary(self.uuid)
        eq_(data['contrib'].pk, self.contrib.pk)
        eq_(data['is_refundable'], True)

        self.create_test_refund()
        data = _transaction_summary(self.uuid)
        eq_(data['is_refundable'], False)

    @mock.patch('mkt.lookup.views.client')
    def test_200(self, solitude):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_no_perm_403(self):
        self.client.login(username='regular@mozilla.com',
                          password='password')
        r = self.client.get(self.url)
        eq_(r.status_code, 403)

        assert self.client.login(username='operator@mozilla.com',
                                 password='password')
        r = self.client.get(self.url)
        eq_(r.status_code, 403)

    def test_no_transaction_404(self):
        r = self.client.get(reverse('lookup.transaction_summary', args=[999]))
        eq_(r.status_code, 404)


@mock.patch.object(settings, 'TASK_USER_ID', 999)
class TestTransactionRefund(TestCase):
    fixtures = fixture('user_support_staff', 'user_999')

    def setUp(self):
        self.uuid = 'paymentuuid'
        self.refund_uuid = 'refunduuid'
        self.summary_url = reverse('lookup.transaction_summary',
                                   args=[self.uuid])
        self.url = reverse('lookup.transaction_refund', args=[self.uuid])
        self.app = app_factory()
        self.user = UserProfile.objects.get(username='regularuser')
        AddonUser.objects.create(addon=self.app, user=self.user)

        self.req = self.request({'refund_reason': 'text'})
        self.contrib = Contribution.objects.create(
            addon=self.app, user=self.user, uuid=self.uuid,
            type=amo.CONTRIB_PURCHASE, amount=1, transaction_id='123')
        # Fix Django 1.4 RequestFactory bug with MessageMiddleware.
        setattr(self.req, 'session', 'session')
        messages = FallbackStorage(self.req)
        setattr(self.req, '_messages', messages)
        self.login(self.req.user)

    def bango_ret(self, status):
        return {
            'status': status,
            'transaction': 'transaction_uri',
            'uuid': 'some:uid'
        }

    def request(self, data):
        req = RequestFactory().post(self.url, data)
        req.user = User.objects.get(username='support_staff')
        req.amo_user = UserProfile.objects.get(username='support_staff')
        req.groups = req.amo_user.groups.all()
        return req

    def refund_tx_ret(self):
        return {'uuid': self.refund_uuid}

    @mock.patch('mkt.lookup.views.client')
    def test_fake_refund_ignored(self, client):
        req = self.request({'refund_reason': 'text', 'fake': 'OK'})
        with self.settings(BANGO_FAKE_REFUNDS=False):
            transaction_refund(req, self.uuid)
        client.api.bango.refund.post.assert_called_with(
            {'uuid': '123', 'manual': False})

    @mock.patch('mkt.lookup.views.client')
    def test_manual_refund(self, client):
        req = self.request({'refund_reason': 'text', 'manual': True})
        transaction_refund(req, self.uuid)
        client.api.bango.refund.post.assert_called_with(
            {'uuid': '123', 'manual': True})

    @mock.patch('mkt.lookup.views.client')
    def test_fake_refund(self, client):
        req = self.request({'refund_reason': 'text', 'fake': 'OK'})
        with self.settings(BANGO_FAKE_REFUNDS=True):
            transaction_refund(req, self.uuid)
        client.api.bango.refund.post.assert_called_with({
            'fake_response_status': {'responseCode': 'OK'},
            'uuid': '123', 'manual': False})

    @mock.patch('mkt.lookup.views.client')
    def test_refund_success(self, solitude):
        solitude.api.bango.refund.post.return_value = self.bango_ret(PENDING)
        solitude.get.return_value = self.refund_tx_ret()

        # Do refund.
        res = transaction_refund(self.req, self.uuid)
        refund = Refund.objects.filter(contribution__addon=self.app)
        refund_contribs = self.contrib.get_refund_contribs()

        # Check Refund created.
        assert refund.exists()
        eq_(refund[0].status, amo.REFUND_PENDING)
        assert self.req.POST['refund_reason'] in refund[0].refund_reason

        # Check refund Contribution created.
        eq_(refund_contribs.exists(), True)
        eq_(refund_contribs[0].refund, refund[0])
        eq_(refund_contribs[0].related, self.contrib)
        eq_(refund_contribs[0].amount, -self.contrib.amount)

        self.assert3xx(res, self.summary_url)

    @mock.patch('mkt.lookup.views.client')
    def test_refund_failed(self, solitude):
        solitude.api.bango.refund.post.return_value = self.bango_ret(FAILED)

        res = transaction_refund(self.req, self.uuid)

        # Check no refund Contributions created.
        assert not self.contrib.get_refund_contribs().exists()
        self.assert3xx(res, self.summary_url)

    def test_cant_refund(self):
        self.contrib.update(type=amo.CONTRIB_PENDING)
        resp = self.client.post(self.url, {'refund_reason': 'text'})
        eq_(resp.status_code, 404)

    @mock.patch('mkt.lookup.views.client')
    def test_already_refunded(self, solitude):
        solitude.api.bango.refund.post.return_value = self.bango_ret(PENDING)
        solitude.get.return_value = self.refund_tx_ret()
        res = transaction_refund(self.req, self.uuid)
        refund_count = Contribution.objects.all().count()

        # Check no refund Contributions created.
        res = self.client.post(self.url, {'refund_reason': 'text'})
        assert refund_count == Contribution.objects.all().count()
        self.assert3xx(res, reverse('lookup.transaction_summary',
                                    args=[self.uuid]))

    @mock.patch('mkt.lookup.views.client')
    def test_refund_slumber_error(self, solitude):
        for exception in (exceptions.HttpClientError,
                          exceptions.HttpServerError):
            solitude.api.bango.refund.post.side_effect = exception
            res = transaction_refund(self.req, self.uuid)

            # Check no refund Contributions created.
            assert not self.contrib.get_refund_contribs().exists()
            self.assert3xx(res, self.summary_url)

    @mock.patch('mkt.lookup.views.client')
    def test_redirect(self, solitude):
        solitude.api.bango.refund.post.return_value = self.bango_ret(PENDING)
        solitude.get.return_value = self.refund_tx_ret()

        res = self.client.post(self.url, {'refund_reason': 'text'})
        self.assert3xx(res, reverse('lookup.transaction_summary',
                                    args=[self.uuid]))

    @mock.patch('mkt.lookup.views.client')
    @mock.patch.object(settings, 'SEND_REAL_EMAIL', True)
    def test_refund_pending_email(self, solitude):
        solitude.api.bango.refund.post.return_value = self.bango_ret(PENDING)
        solitude.get.return_value = self.refund_tx_ret()

        transaction_refund(self.req, self.uuid)
        eq_(len(mail.outbox), 1)
        assert self.app.name.localized_string in smart_str(mail.outbox[0].body)

    @mock.patch('mkt.lookup.views.client')
    @mock.patch.object(settings, 'SEND_REAL_EMAIL', True)
    def test_refund_completed_email(self, solitude):
        solitude.api.bango.refund.post.return_value = self.bango_ret(COMPLETED)
        solitude.get.return_value = self.refund_tx_ret()

        transaction_refund(self.req, self.uuid)
        eq_(len(mail.outbox), 1)
        assert self.app.name.localized_string in smart_str(mail.outbox[0].body)

    @mock.patch('mkt.lookup.views.client')
    def test_403_reg_user(self, solitude):
        solitude.api.bango.refund.post.return_value = self.bango_ret(PENDING)
        solitude.get.return_value = self.refund_tx_ret()

        self.login(self.user)
        res = self.client.post(self.url, {'refund_reason': 'text'})
        eq_(res.status_code, 403)


class TestAppSearch(ESTestCase, SearchTestMixin):
    fixtures = fixture('user_support_staff', 'user_999', 'webapp_337141',
                       'user_operator')

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
        self.refresh('webapp')
        data = self.search(q='steamcube')
        self.verify_result(data)

    def test_by_name_unreviewed(self):
        # Just the same as the above test, but with an unreviewed app.
        self.app.status = amo.STATUS_UNREVIEWED
        self.test_by_name_part()

    def test_by_deleted_app(self):
        self.app.delete()
        self.refresh('webapp')
        data = self.search(q='something')
        self.verify_result(data)

    def test_multiword(self):
        self.app.name = 'Firefox Marketplace'
        self.app.save()
        self.refresh('webapp')
        data = self.search(q='Firefox Marketplace')
        self.verify_result(data)

    def test_by_stem_name(self):
        self.app.name = 'Instigated'
        self.app.save()
        self.refresh('webapp')
        data = self.search(q='instigate')
        self.verify_result(data)

    def test_by_guid(self):
        self.app.update(guid='abcdef', type=amo.ADDON_EXTENSION)
        data = self.search(q=self.app.guid, type=amo.ADDON_EXTENSION)
        self.verify_result(data)

    def test_by_id(self):
        data = self.search(q=self.app.pk)
        self.verify_result(data)

    def test_operator(self):
        assert self.client.login(username='operator@mozilla.com',
                                 password='password')
        data = self.search(q=self.app.pk)
        self.verify_result(data)

    @mock.patch('mkt.constants.lookup.SEARCH_LIMIT', 2)
    @mock.patch('mkt.constants.lookup.MAX_RESULTS', 3)
    def test_all_results(self):
        for x in range(4):
            addon_factory(name='chr' + str(x), type=amo.ADDON_WEBAPP)
        self.refresh('webapp')

        # Test search limit.
        data = self.search(q='chr')
        eq_(len(data['results']), 2)

        # Test maximum search result.
        data = self.search(q='chr', all_results=True)
        eq_(len(data['results']), 3)


class AppSummaryTest(TestCase):
    # TODO: Override in subclasses to convert to new fixture style.
    fixtures = ['base/users', 'base/addon_3615', 'market/prices'
    ] + fixture('webapp_337141')

    def _setUp(self):
        self.app = Addon.objects.get(pk=337141)
        self.url = reverse('lookup.app_summary',
                           args=[self.app.pk])
        self.user = UserProfile.objects.get(username='31337')
        assert self.client.login(username='support-staff@mozilla.com',
                                 password='password')

    def summary(self, expected_status=200):
        res = self.client.get(self.url)
        eq_(res.status_code, expected_status)
        return res


class TestAppSummary(AppSummaryTest):
    fixtures = fixture('prices', 'user_admin', 'user_support_staff',
                       'webapp_337141', 'user_operator')

    def setUp(self):
        super(TestAppSummary, self).setUp()
        self._setUp()

    def test_app_deleted(self):
        self.app.delete()
        self.summary()

    def test_packaged_app_deleted(self):
        self.app.update(is_packaged=True)
        ver = amo.tests.version_factory(addon=self.app)
        amo.tests.file_factory(version=ver)
        self.app.delete()
        self.summary()

    def test_search_matches_type(self):
        res = self.summary()
        eq_(pq(res.content)('#app-search-form select option[selected]').val(),
            str(amo.ADDON_WEBAPP))

    def test_authors(self):
        user = UserProfile.objects.get(username='31337')
        role = AddonUser.objects.create(user=user,
                                        addon=self.app,
                                        role=amo.AUTHOR_ROLE_DEV)
        self.app.addonuser_set.add(role)
        res = self.summary()
        eq_(res.context['authors'][0].display_name, user.display_name)

    def test_visible_authors(self):
        AddonUser.objects.all().delete()
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
        self.make_premium(self.app)
        res = self.summary()
        eq_(res.context['price'], self.app.premium.price)

    def test_abuse_reports(self):
        for i in range(2):
            AbuseReport.objects.create(addon=self.app,
                                       ip_address='10.0.0.1',
                                       message='spam and porn everywhere')
        res = self.summary()
        eq_(res.context['abuse_reports'], 2)

    def test_permissions(self):
        raise SkipTest('we do not support permissions yet')

    def test_version_history_non_packaged(self):
        res = self.summary()
        eq_(pq(res.content)('section.version-history').length, 0)

    def test_version_history_packaged(self):
        self.app.update(is_packaged=True)
        self.version = self.app.current_version
        self.file = self.version.all_files[0]
        self.file.update(filename='mozball.zip')

        res = self.summary()
        eq_(pq(res.content)('section.version-history').length, 1)
        assert 'mozball.zip' in pq(res.content)(
            'section.version-history a.download').attr('href')

    def test_edit_link_staff(self):
        res = self.summary()
        eq_(pq(res.content)('.shortcuts li').length, 4)
        eq_(pq(res.content)('.shortcuts li').eq(3).text(), 'Edit Listing')

    def test_operator_200(self):
        assert self.client.login(username='operator@mozilla.com',
                                 password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)


class TestAppSummaryPurchases(AppSummaryTest):

    def setUp(self):
        super(TestAppSummaryPurchases, self).setUp()
        self._setUp()

    def assert_totals(self, data):
        eq_(data['total'], 6)
        six_bucks = numbers.format_currency(6, 'USD',
                                            locale=numbers.LC_NUMERIC)
        three_euro = numbers.format_currency(3, 'EUR',
                                             locale=numbers.LC_NUMERIC)
        eq_(set(data['amounts']), set([six_bucks, three_euro]))
        eq_(len(data['amounts']), 2)

    def assert_empty(self, data):
        eq_(data['total'], 0)
        eq_(sorted(data['amounts']), [])

    def purchase(self, created=None, typ=amo.CONTRIB_PURCHASE):
        for curr, amount in (('USD', '2.00'), ('EUR', '1.00')):
            for i in range(3):
                c = Contribution.objects.create(addon=self.app,
                                                user=self.user,
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
                    amo.CONTRIB_PENDING]:
            self.purchase(typ=typ)
        res = self.summary()
        self.assert_empty(res.context['purchases']['alltime'])


class TestAppSummaryRefunds(AppSummaryTest):

    def setUp(self):
        super(TestAppSummaryRefunds, self).setUp()
        self._setUp()
        self.user = UserProfile.objects.get(username='regularuser')
        self.contrib1 = self.purchase()
        self.contrib2 = self.purchase()
        self.contrib3 = self.purchase()
        self.contrib4 = self.purchase()

    def purchase(self):
        return Contribution.objects.create(addon=self.app,
                                           user=self.user,
                                           amount=Decimal('0.99'),
                                           currency='USD',
                                           paykey='AP-1235',
                                           type=amo.CONTRIB_PURCHASE)

    def refund(self, refunds):
        for contrib, status in refunds:
            Refund.objects.create(contribution=contrib,
                                  status=status,
                                  user=self.user)

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


class TestAddonDownloadSummary(AppSummaryTest):
    fixtures = fixture('user_admin', 'group_admin', 'user_admin_group',
                       'user_999')

    def setUp(self):
        super(TestAddonDownloadSummary, self).setUp()
        self.users = [UserProfile.objects.get(username='regularuser'),
                      UserProfile.objects.get(username='admin')]
        self.addon = addon_factory()
        self.url = reverse('lookup.app_summary', args=[self.addon.pk])
        self.login(self.users[1])

    def test_7_days(self):
        for user in self.users:
            DownloadCount.objects.create(addon=self.addon, count=2,
                                         date=datetime.now().date())
        res = self.summary()
        eq_(res.context['downloads']['last_7_days'], 4)

    def test_ignore_older_than_7_days(self):
        _8_days_ago = datetime.now() - timedelta(days=8)
        for user in self.users:
            c = DownloadCount.objects.create(addon=self.addon, count=2,
                                             date=datetime.now().date())
            c.date = _8_days_ago.date()
            c.save()
        res = self.summary()
        eq_(res.context['downloads']['last_7_days'], 0)

    def test_24_hours(self):
        for user in self.users:
            DownloadCount.objects.create(addon=self.addon, count=2,
                                         date=datetime.now().date())
        res = self.summary()
        eq_(res.context['downloads']['last_24_hours'], 4)

    def test_ignore_older_than_24_hours(self):
        yesterday = datetime.now().date() - timedelta(days=1)
        for user in self.users:
            c = DownloadCount.objects.create(addon=self.addon, count=2,
                                             date=datetime.now().date())
            c.date = yesterday
            c.save()
        res = self.summary()
        eq_(res.context['downloads']['last_24_hours'], 0)

    def test_alltime_dl(self):
        for i in range(2):
            DownloadCount.objects.create(addon=self.addon, count=2,
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
    fixtures = ['base/users'] + fixture('webapp_337141')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.reviewer = UserProfile.objects.get(username='admin')
        self.user = UserProfile.objects.get(username='regularuser')
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
        eq_(pq(res.content)('p.notice').length, 1)

    def test_purchase_shows_up(self):
        Contribution.objects.create(user=self.user, addon=self.app,
                                    amount=1, type=amo.CONTRIB_PURCHASE)
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('div.product-lookup-list a').attr('href'),
            self.app.get_detail_url())

    def test_no_support_link(self):
        for type_ in [amo.CONTRIB_PURCHASE]:
            Contribution.objects.create(user=self.user, addon=self.app,
                                        amount=1, type=type_)
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(len(doc('.item a.request-support')), 0)


class TestActivity(amo.tests.TestCase):
    fixtures = ['base/users'] + fixture('webapp_337141')

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.reviewer = UserProfile.objects.get(username='admin')
        self.user = UserProfile.objects.get(username='regularuser')
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
