# -*- coding: utf-8 -*-
import datetime
import json
import os
from contextlib import contextmanager
from decimal import Decimal

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage

from nose import SkipTest
import mock
import waffle
from dateutil.parser import parse as parse_dt
from nose.plugins.attrib import attr
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
import paypal
from addons.models import Addon, AddonUpsell, AddonUser
from amo.helpers import babel_datetime, timesince
from amo.tests import assert_no_validation_errors
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from amo.utils import urlparams
from browse.tests import test_default_sort, test_listing_sort
from devhub.models import UserLog
from files.models import FileUpload
from files.tests.test_models import UploadTest as BaseUploadTest
from market.models import AddonPremium, Price, Refund
from mkt.developers import tasks
from mkt.developers.models import ActivityLog
from mkt.submit.models import AppSubmissionChecklist
from mkt.webapps.models import Webapp
from paypal import PaypalError
from paypal.check import Check
from stats.models import Contribution
from translations.models import Translation
from users.models import UserProfile


class AppHubTest(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.url = reverse('mkt.developers.apps')
        self.user = UserProfile.objects.get(username='31337')
        assert self.client.login(username=self.user.email, password='password')

    def clone_addon(self, num, addon_id=337141):
        ids = []
        for i in xrange(num):
            addon = Addon.objects.get(id=addon_id)
            new_addon = Addon.objects.create(type=addon.type,
                status=addon.status, name='cloned-addon-%s-%s' % (addon_id, i))
            AddonUser.objects.create(user=self.user, addon=new_addon)
            ids.append(new_addon.id)
        return ids

    def get_app(self):
        return Addon.objects.get(id=337141)


class TestHome(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.url = reverse('mkt.developers.apps')

    def test_legacy_login_redirect(self):
        r = self.client.get('/users/login')
        got, exp = r['Location'], '/login'
        assert got.endswith(exp), 'Expected %s. Got %s.' % (exp, got)

    def test_login_redirect(self):
        self.skip_if_disabled(settings.REGION_STORES)
        r = self.client.get(self.url)
        self.assertLoginRedirects(r, '/developers/submissions', 302)

    def test_home_anonymous(self):
        r = self.client.get(self.url, follow=True)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'developers/login.html')

    def test_home_authenticated(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        r = self.client.get(self.url, follow=True)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'developers/apps/dashboard.html')


class TestAppBreadcrumbs(AppHubTest):

    def setUp(self):
        super(TestAppBreadcrumbs, self).setUp()

    def test_regular_breadcrumbs(self):
        r = self.client.get(reverse('submit.app'), follow=True)
        eq_(r.status_code, 200)
        expected = [
            ('Home', reverse('home')),
            ('Developers', reverse('ecosystem.landing')),
            ('Submit App', None),
        ]
        amo.tests.check_links(expected, pq(r.content)('#breadcrumbs li'))

    def test_webapp_management_breadcrumbs(self):
        webapp = Webapp.objects.get(id=337141)
        AddonUser.objects.create(user=self.user, addon=webapp)
        r = self.client.get(webapp.get_dev_url('edit'))
        eq_(r.status_code, 200)
        expected = [
            ('Home', reverse('home')),
            ('Developers', reverse('ecosystem.landing')),
            ('My Submissions', reverse('mkt.developers.apps')),
            (unicode(webapp.name), None),
        ]
        amo.tests.check_links(expected, pq(r.content)('#breadcrumbs li'))


class TestAppDashboard(AppHubTest):

    def setUp(self):
        super(TestAppDashboard, self).setUp()

    def test_no_apps(self):
        Addon.objects.all().delete()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#dashboard .item').length, 0)

    def make_mine(self):
        AddonUser.objects.create(addon_id=337141, user=self.user)

    def test_public_app(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        app = self.get_app()
        self.make_mine()
        doc = pq(self.client.get(self.url).content)
        item = doc('.item[data-addonid=%s]' % app.id)
        assert item.find('.price'), 'Expected price'
        assert item.find('.item-details'), 'Expected item details'
        assert not item.find('p.incomplete'), (
            'Unexpected message about incomplete add-on')
        expected = [
            ('Manage Status', app.get_dev_url('versions')),
        ]
        amo.tests.check_links(expected, doc('.more-actions-popup a'))

    def test_incomplete_app(self):
        app = self.get_app()
        app.update(status=amo.STATUS_NULL)
        self.make_mine()
        doc = pq(self.client.get(self.url).content)
        assert doc('.item[data-addonid=%s] p.incomplete' % app.id), (
            'Expected message about incompleted add-on')
        eq_(doc('.more-actions-popup').length, 0)

    def test_action_links(self):
        waffle.models.Switch.objects.get_or_create(name='app-stats',
                                                   active=True)
        app = self.get_app()
        app.update(public_stats=True)
        self.make_mine()
        doc = pq(self.client.get(self.url).content)
        expected = [
            ('Edit Listing', app.get_dev_url()),
            ('Manage Authors', app.get_dev_url('owner')),
            ('Manage Payments', app.get_dev_url('payments')),
            ('View Listing', app.get_url_path()),
        ]
        amo.tests.check_links(expected, doc('a.action-link'))
        amo.tests.check_links([('View Statistics', app.get_stats_url())],
            doc('a.stats-link'), verify=False)

    def test_action_links_with_payments(self):
        waffle.models.Switch.objects.create(name='allow-refund', active=True)
        waffle.models.Switch.objects.create(name='in-app-payments',
            active=True)
        app = self.get_app()
        for status in [amo.ADDON_PREMIUM_INAPP, amo.ADDON_FREE_INAPP]:
            app.update(premium_type=status)
            self.make_mine()
            doc = pq(self.client.get(self.url).content)
            expected = [
                ('Manage Status', app.get_dev_url('versions')),
                ('Manage In-App Payments', app.get_dev_url('in_app_config')),
                ('Manage PayPal', app.get_dev_url('paypal_setup')),
                ('Manage Refunds', app.get_dev_url('refunds')),
            ]
            amo.tests.check_links(expected, doc('.more-actions-popup a'))


class TestManageLinks(AppHubTest):

    def setUp(self):
        super(TestManageLinks, self).setUp()
        waffle.models.Switch.objects.create(name='allow-refund', active=True)

    def test_refunds_link_support(self):
        app = self.get_app()
        for status in [amo.ADDON_PREMIUM, amo.ADDON_PREMIUM_INAPP,
                       amo.ADDON_FREE_INAPP]:
            app.update(premium_type=status)

            AddonUser.objects.update(role=amo.AUTHOR_ROLE_SUPPORT)
            assert self.client.login(username=self.user.email,
                                     password='password')

            for url in [self.url, app.get_dev_url()]:
                r = self.client.get(self.url)
                eq_(r.status_code, 200)
                assert 'Manage Refunds' in r.content, (
                    'Expected "Manage Refunds" link')

    def test_refunds_link_viewer(self):
        app = self.get_app()
        for status in [amo.ADDON_PREMIUM, amo.ADDON_PREMIUM_INAPP,
                       amo.ADDON_FREE_INAPP]:
            app.update(premium_type=status)

            AddonUser.objects.update(role=amo.AUTHOR_ROLE_VIEWER)
            assert self.client.login(username=self.user.email,
                                     password='password')

            for url in [self.url, app.get_dev_url()]:
                r = self.client.get(self.url)
                eq_(r.status_code, 200)
                assert 'Manage Refunds' not in r.content, (
                    '"Manage Refunds" link should be hidden')


class TestAppDashboardSorting(AppHubTest):

    def setUp(self):
        super(TestAppDashboardSorting, self).setUp()
        self.my_apps = self.user.addons
        self.url = reverse('mkt.developers.apps')
        self.clone(3)

    def clone(self, num=3):
        for x in xrange(num):
            app = amo.tests.addon_factory(type=amo.ADDON_WEBAPP)
            AddonUser.objects.create(addon=app, user=self.user)

    def test_pagination(self):
        doc = pq(self.client.get(self.url).content)('#dashboard')
        eq_(doc('.item').length, 4)
        eq_(doc('#sorter').length, 1)
        eq_(doc('.paginator').length, 0)

        self.clone(7)  # 4 + 7 = 11 (paginator appears for 11+ results)
        doc = pq(self.client.get(self.url).content)('#dashboard')
        eq_(doc('.item').length, 10)
        eq_(doc('#sorter').length, 1)
        eq_(doc('.paginator').length, 1)

        doc = pq(self.client.get(self.url, dict(page=2)).content)('#dashboard')
        eq_(doc('.item').length, 1)
        eq_(doc('#sorter').length, 1)
        eq_(doc('.paginator').length, 1)

    def test_default_sort(self):
        test_default_sort(self, 'name', 'name', reverse=False)

    def test_newest_sort(self):
        test_listing_sort(self, 'created', 'created')


class TestDevRequired(AppHubTest):

    def setUp(self):
        self.webapp = Addon.objects.get(id=337141)
        self.get_url = self.webapp.get_dev_url('payments')
        self.post_url = self.webapp.get_dev_url('payments.disable')
        self.user = UserProfile.objects.get(username='31337')
        assert self.client.login(username=self.user.email, password='password')
        self.au = AddonUser.objects.get(user=self.user, addon=self.webapp)
        eq_(self.au.role, amo.AUTHOR_ROLE_OWNER)

    def test_anon(self):
        self.client.logout()
        r = self.client.get(self.get_url, follow=True)
        login = reverse('users.login')
        self.assertRedirects(r, '%s?to=%s' % (login, self.get_url))

    def test_dev_get(self):
        eq_(self.client.get(self.get_url).status_code, 200)

    def test_dev_post(self):
        self.assertRedirects(self.client.post(self.post_url), self.get_url)

    def test_viewer_get(self):
        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        eq_(self.client.get(self.get_url).status_code, 200)

    def test_viewer_post(self):
        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        eq_(self.client.post(self.get_url).status_code, 403)

    def test_disabled_post_dev(self):
        self.webapp.update(status=amo.STATUS_DISABLED)
        eq_(self.client.post(self.get_url).status_code, 403)

    def test_disabled_post_admin(self):
        self.webapp.update(status=amo.STATUS_DISABLED)
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.assertRedirects(self.client.post(self.post_url), self.get_url)


class TestEditPayments(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.addon = self.get_addon()
        self.url = self.addon.get_dev_url('payments')
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        self.paypal_mock = mock.Mock()
        self.paypal_mock.return_value = (True, None)
        paypal.check_paypal_id = self.paypal_mock

    def get_addon(self):
        return Addon.objects.get(id=337141)

    @mock.patch('addons.models.Addon.upsell')
    def test_upsell(self, upsell):
        upsell.return_value = self.get_addon()
        d = dict(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                 annoying=amo.CONTRIB_AFTER, premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.url, d)
        eq_('premium app' in res.content, True)


class TestPaymentsProfile(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.addon = Addon.objects.get(id=337141)
        AddonUser.objects.create(addon=self.addon,
                                 user=UserProfile.objects.get(pk=999))
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.url = self.addon.get_dev_url('paypal_setup_check')

    def test_checker_no_paypal_id(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        result = json.loads(res.content)
        eq_(result['valid'], False)

    @mock.patch.object(Check, 'all')
    def test_checker_pass(self, all_):
        self.addon.update(paypal_id='a@a.com')
        Check.passed = True

        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        result = json.loads(res.content)
        eq_(result['valid'], True)

    @mock.patch.object(Check, 'all')
    def test_checker_error(self, all_):
        self.addon.update(paypal_id='a@a.com')
        Check.passed = False

        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        result = json.loads(res.content)
        eq_(result[u'valid'], False)

    @mock.patch('mkt.developers.views.client')
    def test_checker_solitude(self, client):
        self.create_flag(name='solitude-payments')
        client.post_account_check.return_value = {'passed': True,
                                                  'errors': []}
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        result = json.loads(res.content)
        eq_(result['valid'], True)


class MarketplaceMixin(object):

    def setUp(self):
        self.addon = Addon.objects.get(id=337141)
        self.addon.update(status=amo.STATUS_NOMINATED,
            highest_status=amo.STATUS_NOMINATED)

        self.url = self.addon.get_dev_url('payments')
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')

        self.marketplace = (waffle.models.Switch.objects
                                  .get_or_create(name='marketplace')[0])
        self.marketplace.active = True
        self.marketplace.save()

    def tearDown(self):
        self.marketplace.active = False
        self.marketplace.save()

    def setup_premium(self):
        self.price = Price.objects.create(price='0.99')
        self.price_two = Price.objects.create(price='1.99')
        self.other_addon = Addon.objects.create(type=amo.ADDON_WEBAPP,
                                                premium_type=amo.ADDON_FREE)
        self.other_addon.update(status=amo.STATUS_PUBLIC)
        AddonUser.objects.create(addon=self.other_addon,
                                 user=self.addon.authors.all()[0])
        AddonPremium.objects.create(addon=self.addon, price_id=self.price.pk)
        self.addon.update(premium_type=amo.ADDON_PREMIUM,
                          paypal_id='a@a.com')


# Mock out verifying the paypal id has refund permissions with paypal and
# that the account exists on paypal.
#
@mock.patch('mkt.developers.forms.PremiumForm.clean',
             new=lambda x: x.cleaned_data)
class TestMarketplace(MarketplaceMixin, amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def get_data(self, **kw):
        data = {
            'price': self.price.pk,
            'free': self.other_addon.pk,
            'do_upsell': 1,
            'text': 'some upsell',
            'premium_type': amo.ADDON_PREMIUM,
            'support_email': 'c@c.com',
        }
        data.update(kw)
        return data

    def test_initial(self):
        self.setup_premium()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(res.context['form'].initial['price'], self.price)

    def test_set(self):
        self.setup_premium()
        res = self.client.post(self.url, data={
            'support_email': 'c@c.com',
            'price': self.price_two.pk,
            'premium_type': amo.ADDON_PREMIUM
        })
        eq_(res.status_code, 302)
        self.addon = Addon.objects.get(pk=self.addon.pk)
        eq_(self.addon.addonpremium.price, self.price_two)

    def test_set_upsell(self):
        self.setup_premium()
        res = self.client.post(self.url, data=self.get_data())
        eq_(res.status_code, 302)
        eq_(len(self.addon._upsell_to.all()), 1)

    def test_set_upsell_wrong_status(self):
        self.setup_premium()
        self.other_addon.update(status=amo.STATUS_NULL)
        res = self.client.post(self.url, data=self.get_data())
        eq_(res.status_code, 200)

    def test_set_upsell_wrong_type(self):
        self.setup_premium()
        self.other_addon.update(type=amo.ADDON_EXTENSION)
        res = self.client.post(self.url, data=self.get_data())
        eq_(res.status_code, 200)
        eq_(len(res.context['form'].errors['free']), 1)
        eq_(len(self.addon._upsell_to.all()), 0)

    def test_set_upsell_required(self):
        self.setup_premium()
        res = self.client.post(self.url, data=self.get_data(text=''))
        eq_(res.status_code, 200)

    def test_set_upsell_not_mine(self):
        self.setup_premium()
        self.other_addon.authors.clear()
        res = self.client.post(self.url, data=self.get_data())
        eq_(res.status_code, 200)

    def test_remove_upsell(self):
        self.setup_premium()
        upsell = AddonUpsell.objects.create(free=self.other_addon,
                                            premium=self.addon)
        eq_(self.addon._upsell_to.all()[0], upsell)
        self.client.post(self.url, data=self.get_data(do_upsell=0))
        eq_(len(self.addon._upsell_to.all()), 0)

    def test_change_upsell(self):
        self.setup_premium()
        AddonUpsell.objects.create(free=self.other_addon,
                                   premium=self.addon, text='foo')
        eq_(self.addon._upsell_to.all()[0].text, 'foo')
        self.client.post(self.url, data=self.get_data(text='bar'))
        eq_(self.addon._upsell_to.all()[0].text, 'bar')

    def test_replace_upsell(self):
        self.setup_premium()
        # Make this add-on an upsell of some free add-on.
        AddonUpsell.objects.create(free=self.other_addon,
                                   premium=self.addon, text='foo')
        # And this will become our new upsell, replacing the one above.
        new = Addon.objects.create(type=amo.ADDON_WEBAPP,
                                   premium_type=amo.ADDON_FREE)
        new.update(status=amo.STATUS_PUBLIC)
        AddonUser.objects.create(addon=new, user=self.addon.authors.all()[0])

        eq_(self.addon._upsell_to.all()[0].text, 'foo')
        self.client.post(self.url, self.get_data(free=new.id, text='bar'))
        upsell = self.addon._upsell_to.all()
        eq_(len(upsell), 1)
        eq_(upsell[0].free, new)
        eq_(upsell[0].text, 'bar')

    def test_no_free(self):
        self.setup_premium()
        self.other_addon.authors.clear()
        res = self.client.get(self.url)
        assert not pq(res.content)('#id_free')

    @mock.patch('paypal.get_permissions_token', lambda x, y: x.upper())
    @mock.patch('paypal.get_personal_data', lambda x: {'email': 'a@a.com'})
    def test_permissions_token(self):
        self.setup_premium()
        eq_(self.addon.premium.paypal_permissions_token, '')
        url = self.addon.get_dev_url('acquire_refund_permission')
        self.client.get(urlparams(url, request_token='foo',
                                       verification_code='bar'))
        self.addon = Addon.objects.get(pk=self.addon.pk)
        eq_(self.addon.premium.paypal_permissions_token, 'FOO')

    @mock.patch('paypal.get_permissions_token', lambda x, y: x.upper())
    @mock.patch('paypal.get_personal_data', lambda x: {})
    def test_permissions_token_different_email(self):
        self.setup_premium()
        url = self.addon.get_dev_url('acquire_refund_permission')
        self.client.get(urlparams(url, request_token='foo',
                                       verification_code='bar'))
        self.addon = Addon.objects.get(pk=self.addon.pk)
        eq_(self.addon.premium.paypal_permissions_token, '')

    @mock.patch('mkt.developers.views.client')
    def test_permissions_token_solitude(self, client):
        self.create_flag(name='solitude-payments')
        self.setup_premium()
        url = self.addon.get_dev_url('acquire_refund_permission')
        client.post_personal_basic.return_value = {'email': 'a@a.com'}
        res = self.client.get(urlparams(url, request_token='foo',
                                        verification_code='bar'))
        self.assertRedirects(res,
                             self.addon.get_dev_url('paypal_setup_confirm'))

    @mock.patch('mkt.developers.views.client')
    def test_personal_differs_solitude(self, client):
        self.create_flag(name='solitude-payments')
        self.setup_premium()
        url = self.addon.get_dev_url('acquire_refund_permission')
        client.post_personal_basic.side_effect = client.Error
        res = self.client.get(urlparams(url, request_token='foo',
                                        verification_code='bar'))
        self.assertRedirects(res,
                             self.addon.get_dev_url('paypal_setup_bounce'))


class TestIssueRefund(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def logged(self, user, status):
        return (UserLog.objects.filter(user=user,
                                       activity_log__action=status.id)).count()

    def setUp(self):
        waffle.models.Switch.objects.create(name='allow-refund', active=True)
        self.addon = Addon.objects.no_cache().get(id=337141)
        self.transaction_id = u'fake-txn-id'
        self.paykey = u'fake-paykey'
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        self.owner = UserProfile.objects.get(email='steamcube@mozilla.com')
        self.user = UserProfile.objects.get(username='clouserw')
        self.url = self.addon.get_dev_url('issue_refund')

    def make_purchase(self, uuid='123456', type=amo.CONTRIB_PURCHASE):
        return Contribution.objects.create(uuid=uuid, addon=self.addon,
                                           transaction_id=self.transaction_id,
                                           user=self.user, paykey=self.paykey,
                                           amount=Decimal('10'), type=type)

    def test_viewer_lacks_access(self):
        AddonUser.objects.update(role=amo.AUTHOR_ROLE_VIEWER)
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        c = self.make_purchase()
        data = {'transaction_id': c.transaction_id}
        eq_(self.client.get(self.url, data).status_code, 403)
        eq_(self.client.post(self.url, data).status_code, 403)

    def _test_has_access(self, role):
        AddonUser.objects.update(role=role)
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        c = self.make_purchase()
        data = {'transaction_id': c.transaction_id}
        eq_(self.client.get(self.url, data).status_code, 200)
        eq_(self.client.post(self.url, data).status_code, 302)

    def test_support_has_access(self):
        self._test_has_access(amo.AUTHOR_ROLE_SUPPORT)

    def test_dev_has_access(self):
        self._test_has_access(amo.AUTHOR_ROLE_DEV)

    def test_request_issue(self):
        c = self.make_purchase()
        r = self.client.get(self.url, {'transaction_id': c.transaction_id})
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#issue-refund button').length, 2)
        eq_(doc('#issue-refund input[name=transaction_id]').val(),
            self.transaction_id)

    def test_request_issue_inapp(self):
        c = self.make_purchase()
        c.update(type=amo.CONTRIB_INAPP)
        r = self.client.get(self.url, {'transaction_id': c.transaction_id})
        eq_(r.status_code, 200)

    def test_nonexistent_txn(self):
        r = self.client.get(self.url, {'transaction_id': 'none'})
        eq_(r.status_code, 404)

    def test_nonexistent_txn_no_really(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 404)

    def _test_issue(self, refund, enqueue_refund):
        refund.return_value = []
        c = self.make_purchase()
        r = self.client.post(self.url, {'transaction_id': c.transaction_id,
                                        'issue': '1'})
        self.assertRedirects(r, self.addon.get_dev_url('refunds'), 302)
        refund.assert_called_with(self.paykey)
        eq_(len(mail.outbox), 1)
        assert 'approved' in mail.outbox[0].subject
        # There should be one approved refund added.
        eq_(enqueue_refund.call_args_list[0][0], (amo.REFUND_APPROVED,))

    @mock.patch('stats.models.Contribution.enqueue_refund')
    @mock.patch('paypal.refund')
    def test_apps_issue(self, refund, enqueue_refund):
        self._test_issue(refund, enqueue_refund)

    @mock.patch('stats.models.Contribution.enqueue_refund')
    @mock.patch('paypal.refund')
    def test_apps_issue_logs(self, refund, enqueue_refund):
        self._test_issue(refund, enqueue_refund)
        eq_(self.logged(user=self.owner, status=amo.LOG.REFUND_GRANTED), 1)
        eq_(self.logged(user=self.user, status=amo.LOG.REFUND_GRANTED), 1)

    @mock.patch('stats.models.Contribution.enqueue_refund')
    @mock.patch('paypal.refund')
    def test_apps_issue_error(self, refund, enqueue_refund):
        refund.side_effect = PaypalError
        c = self.make_purchase()
        r = self.client.post(self.url, {'transaction_id': c.transaction_id,
                                        'issue': '1'}, follow=True)
        eq_(len(pq(r.content)('.notification-box')), 1)

    def _test_issue_solitude(self, client, enqueue_refund):
        waffle.models.Flag.objects.create(name='solitude-payments',
                                          everyone=True)
        client.post_refund.return_value = {'response': []}

        c = self.make_purchase()
        r = self.client.post(self.url, {'transaction_id': c.transaction_id,
                                        'issue': '1'})
        self.assertRedirects(r, self.addon.get_dev_url('refunds'), 302)
        eq_(client.post_refund.call_args[1]['data']['uuid'], 'fake-txn-id')
        eq_(len(mail.outbox), 1)
        assert 'approved' in mail.outbox[0].subject
        # There should be one approved refund added.
        eq_(enqueue_refund.call_args_list[0][0], (amo.REFUND_APPROVED,))

    @mock.patch('stats.models.Contribution.enqueue_refund')
    @mock.patch('mkt.developers.views.client')
    def test_apps_issue_solitude(self, client, enqueue_refund):
        self._test_issue_solitude(client, enqueue_refund)

    @mock.patch('stats.models.Contribution.enqueue_refund')
    @mock.patch('mkt.developers.views.client')
    def test_apps_issue_solitude_error(self, client, enqueue_refund):
        waffle.models.Flag.objects.create(name='solitude-payments',
                                          everyone=True)

        client.post_refund.side_effect = client.Error
        c = self.make_purchase()
        r = self.client.post(self.url, {'transaction_id': c.transaction_id,
                                        'issue': '1'}, follow=True)
        eq_(len(pq(r.content)('.notification-box')), 1)

    def test_fresh_refund(self):
        c = self.make_purchase()
        Refund.objects.create(contribution=c)
        r = self.client.get(self.url, {'transaction_id': c.transaction_id})
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('.no-results').length, 0)
        eq_(doc('input[name=transaction_id]').val(), c.transaction_id)

    def test_stale_refund(self):
        c = self.make_purchase()
        ref = Refund.objects.create(contribution=c)
        # Any other status means we've already taken action.
        for status in sorted(amo.REFUND_STATUSES.keys())[1:3]:
            ref.update(status=status)
            r = self.client.get(self.url, {'transaction_id': c.transaction_id})
            eq_(r.status_code, 200)
            doc = pq(r.content)
            eq_(doc('.no-results').length, 1,
                'Expected no results for refund of status %r' % status)
            eq_(doc('input[name=transaction_id]').length, 0,
                'Expected form fields for refund of status %r' % status)

    @mock.patch('amo.messages.error')
    @mock.patch('paypal.refund')
    def test_only_one_issue(self, refund, error):
        refund.return_value = []
        c = self.make_purchase()
        self.client.post(self.url,
                         {'transaction_id': c.transaction_id,
                          'issue': '1'})
        r = self.client.get(self.url, {'transaction_id': c.transaction_id})
        assert 'Decline Refund' not in r.content
        assert 'Refund already processed' in error.call_args[0][1]

        self.client.post(self.url,
                         {'transaction_id': c.transaction_id,
                          'issue': '1'})
        eq_(Refund.objects.count(), 1)

    @mock.patch('amo.messages.error')
    @mock.patch('paypal.refund')
    def test_no_issue_after_decline(self, refund, error):
        refund.return_value = []
        c = self.make_purchase()
        self.client.post(self.url,
                         {'transaction_id': c.transaction_id,
                          'decline': ''})
        del self.client.cookies['messages']
        r = self.client.get(self.url, {'transaction_id': c.transaction_id})
        eq_(pq(r.content)('#issue-refund button').length, 0)
        assert 'Refund already processed' in error.call_args[0][1]

        self.client.post(self.url,
                         {'transaction_id': c.transaction_id,
                          'issue': '1'})
        eq_(Refund.objects.count(), 1)
        eq_(Refund.objects.get(contribution=c).status, amo.REFUND_DECLINED)

    def _test_decline(self, refund, enqueue_refund):
        c = self.make_purchase()
        r = self.client.post(self.url, {'transaction_id': c.transaction_id,
                                        'decline': ''})
        self.assertRedirects(r, self.addon.get_dev_url('refunds'), 302)
        assert not refund.called
        eq_(len(mail.outbox), 1)
        assert 'declined' in mail.outbox[0].subject
        # There should be one declined refund added.
        eq_(enqueue_refund.call_args_list[0][0], (amo.REFUND_DECLINED,))

    @mock.patch('stats.models.Contribution.enqueue_refund')
    @mock.patch('paypal.refund')
    def test_apps_decline(self, refund, enqueue_refund):
        self._test_decline(refund, enqueue_refund)

    @mock.patch('stats.models.Contribution.enqueue_refund')
    @mock.patch('paypal.refund')
    def test_apps_decline_logs(self, refund, enqueue_refund):
        self._test_decline(refund, enqueue_refund)
        eq_(self.logged(user=self.owner, status=amo.LOG.REFUND_DECLINED), 1)
        eq_(self.logged(user=self.user, status=amo.LOG.REFUND_DECLINED), 1)

    @mock.patch('stats.models.Contribution.enqueue_refund')
    @mock.patch('paypal.refund')
    def test_non_refundable_txn(self, refund, enqueue_refund):
        c = self.make_purchase('56789', amo.CONTRIB_VOLUNTARY)
        r = self.client.post(self.url, {'transaction_id': c.transaction_id,
                                        'issue': ''})
        eq_(r.status_code, 404)
        assert not refund.called, '`paypal.refund` should not have been called'
        assert not enqueue_refund.called, (
            '`Contribution.enqueue_refund` should not have been called')

    @mock.patch('paypal.refund')
    def test_already_refunded(self, refund):
        refund.return_value = [{'refundStatus': 'ALREADY_REVERSED_OR_REFUNDED',
                                'receiver.email': self.user.email}]
        c = self.make_purchase()
        r = self.client.post(self.url, {'transaction_id': c.transaction_id,
                                        'issue': '1'})
        self.assertRedirects(r, self.addon.get_dev_url('refunds'), 302)
        eq_(len(mail.outbox), 0)
        assert 'previously issued' in r.cookies['messages'].value

    @mock.patch('mkt.developers.views.client')
    def test_already_refunded_solitude(self, client):
        waffle.models.Flag.objects.create(name='solitude-payments',
                                          everyone=True)

        client.post_refund.return_value = {'response': [{
                'refundStatus': 'ALREADY_REVERSED_OR_REFUNDED',
                'receiver.email': self.user.email}]}
        c = self.make_purchase()
        r = self.client.post(self.url, {'transaction_id': c.transaction_id,
                                        'issue': '1'})
        self.assertRedirects(r, self.addon.get_dev_url('refunds'), 302)
        eq_(len(mail.outbox), 0)
        assert 'previously issued' in r.cookies['messages'].value

    @mock.patch('paypal.refund')
    def test_no_api_key(self, refund):
        refund.return_value = [{'refundStatus': 'NO_API_ACCESS_TO_RECEIVER',
                                'receiver.email': self.user.email}]
        c = self.make_purchase()
        r = self.client.post(self.url, {'transaction_id': c.transaction_id,
                                        'issue': '1'})
        self.assertRedirects(r, self.addon.get_dev_url('refunds'), 302)
        eq_(len(mail.outbox), 0)
        assert 'try again later' in r.cookies['messages'].value

    @mock.patch('stats.models.Contribution.record_failed_refund')
    @mock.patch('paypal.refund')
    def test_refund_failed(self, refund, record):
        err = paypal.PaypalError('transaction died in a fire')

        def fail(*args, **kwargs):
            raise err

        refund.side_effect = fail
        c = self.make_purchase()
        r = self.client.post(self.url, {'transaction_id': c.transaction_id,
                                        'issue': '1'})
        record.assert_called_once_with(err)
        self.assertRedirects(r, self.addon.get_dev_url('refunds'), 302)


class TestRefunds(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        waffle.models.Switch.objects.create(name='allow-refund', active=True)
        self.webapp = Addon.objects.get(id=337141)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        self.user = UserProfile.objects.get(username='31337')
        self.client.login(username=self.user.email, password='password')
        self.url = self.webapp.get_dev_url('refunds')
        self.queues = {
            'pending': amo.REFUND_PENDING,
            'approved': amo.REFUND_APPROVED,
            'instant': amo.REFUND_APPROVED_INSTANT,
            'declined': amo.REFUND_DECLINED,
        }

    def generate_refunds(self):
        days_ago = lambda days: (datetime.datetime.today() -
                                 datetime.timedelta(days=days))
        self.expected = {}
        for status in amo.REFUND_STATUSES.keys():
            for x in xrange(status + 2):
                c = Contribution.objects.create(addon=self.webapp,
                    user=self.user, type=amo.CONTRIB_PURCHASE)
                r = Refund.objects.create(contribution=c, status=status,
                                          requested=days_ago(x))
                self.expected.setdefault(status, []).append(r)

    def test_anonymous(self):
        self.client.logout()
        r = self.client.get(self.url, follow=True)
        self.assertLoginRedirects(r, self.url)

    def test_viewer(self):
        AddonUser.objects.update(role=amo.AUTHOR_ROLE_VIEWER)
        assert self.client.login(username=self.user.email, password='password')
        eq_(self.client.get(self.url).status_code, 403)

    def test_support(self):
        AddonUser.objects.update(role=amo.AUTHOR_ROLE_SUPPORT)
        assert self.client.login(username=self.user.email, password='password')
        eq_(self.client.get(self.url).status_code, 200)

    def test_bad_owner(self):
        self.client.logout()
        self.client.login(username='regular@mozilla.com', password='password')
        eq_(self.client.get(self.url).status_code, 403)

    def test_owner(self):
        eq_(self.client.get(self.url).status_code, 200)

    def test_admin(self):
        self.client.logout()
        self.client.login(username='admin@mozilla.com', password='password')
        eq_(self.client.get(self.url).status_code, 200)

    def test_not_premium(self):
        for status in [amo.ADDON_FREE, amo.ADDON_OTHER_INAPP]:
            self.webapp.update(premium_type=status)
            r = self.client.get(self.url)
            eq_(r.status_code, 200)
            eq_(pq(r.content)('#enable-payments').length, 1)

    def test_is_premium(self):
        for status in [amo.ADDON_PREMIUM, amo.ADDON_PREMIUM_INAPP,
                       amo.ADDON_FREE_INAPP]:
            self.webapp.update(premium_type=status)
            r = self.client.get(self.url)
            eq_(r.status_code, 200)
            eq_(pq(r.content)('#enable-payments').length, 0)

    def test_empty_queues(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        for key, status in self.queues.iteritems():
            eq_(list(r.context[key]), [])

    def test_queues(self):
        self.generate_refunds()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        for key, status in self.queues.iteritems():
            eq_(set(r.context[key]), set(self.expected[status]))

    def test_empty_tables(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        for key in self.queues.keys():
            eq_(doc('.no-results#queue-%s' % key).length, 1)

    def test_tables(self):
        self.generate_refunds()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#enable-payments').length, 0)
        for key in self.queues.keys():
            table = doc('#queue-%s' % key)
            eq_(table.length, 1)

    def test_timestamps(self):
        self.generate_refunds()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)

        # Pending timestamps should be relative.
        table = doc('#queue-pending')
        for refund in self.expected[amo.REFUND_PENDING]:
            tr = table.find('.refund[data-refundid=%s]' % refund.id)
            purchased = tr.find('.purchased-date')
            requested = tr.find('.requested-date')
            eq_(purchased.text(),
                timesince(refund.contribution.created).strip())
            eq_(requested.text(),
                timesince(refund.requested).strip())
            eq_(purchased.attr('title'),
                babel_datetime(refund.contribution.created).strip())
            eq_(requested.attr('title'),
                babel_datetime(refund.requested).strip())

        # Remove pending table.
        table.remove()

        # All other timestamps should be absolute.
        table = doc('table')
        others = Refund.objects.exclude(status__in=(amo.REFUND_PENDING,
                                                    amo.REFUND_FAILED))
        for refund in others:
            tr = table.find('.refund[data-refundid=%s]' % refund.id)
            eq_(tr.find('.purchased-date').text(),
                babel_datetime(refund.contribution.created).strip())
            eq_(tr.find('.requested-date').text(),
                babel_datetime(refund.requested).strip())

    def test_refunds_sorting(self):
        self.generate_refunds()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)

        for queue in self.queues.keys():
            prev_dt = None
            for req in doc('#queue-%s .requested-date' % queue):
                req = pq(req)
                if queue == 'pending':
                    # Pending queue is sorted by requested ascending.
                    req_dt = parse_dt(req.attr('title'))
                    if prev_dt:
                        assert req_dt > prev_dt, (
                            'Requested date should be sorted ascending for the'
                            ' pending refund queue')
                else:
                    # The other tables are sorted by requested descending.
                    req_dt = parse_dt(req.text())
                    if prev_dt:
                        assert req_dt < prev_dt, (
                            'Requested date should be sorted descending for '
                            'all queues except for pending refunds.')
                prev_dt = req_dt


class TestPublicise(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.webapp.update(status=amo.STATUS_PUBLIC_WAITING)
        self.publicise_url = self.webapp.get_dev_url('publicise')
        self.status_url = self.webapp.get_dev_url('versions')
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')

    def get_webapp(self):
        return Addon.objects.no_cache().get(id=337141)

    def test_logout(self):
        self.client.logout()
        res = self.client.post(self.publicise_url)
        eq_(res.status_code, 302)
        eq_(self.get_webapp().status, amo.STATUS_PUBLIC_WAITING)

    def test_publicise(self):
        res = self.client.post(self.publicise_url)
        eq_(res.status_code, 302)
        eq_(self.get_webapp().status, amo.STATUS_PUBLIC)

    def test_status(self):
        res = self.client.get(self.status_url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(doc('#version-status form').attr('action'), self.publicise_url)
        # TODO: fix this when jenkins can get the jinja helpers loaded in
        # the correct order.
        #eq_(len(doc('strong.status-waiting')), 1)


class TestDelete(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_dev_url('delete')
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')

    def get_webapp(self):
        return Addon.objects.no_cache().get(id=337141)

    def test_post_not(self):
        # Update this test when BrowserID re-auth is available.
        r = self.client.post(self.url, follow=True)
        eq_(pq(r.content)('.notification-box').text(),
            'Paid apps cannot be deleted. Disable this app instead.')

    def test_post(self):
        waffle.models.Switch.objects.create(name='soft_delete', active=True)
        r = self.client.post(self.url, follow=True)
        eq_(pq(r.content)('.notification-box').text(), 'App deleted.')
        self.assertRaises(Addon.DoesNotExist, self.get_webapp)


class TestProfileBase(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.version = self.webapp.current_version
        self.url = self.webapp.get_dev_url('profile')
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')

    def get_webapp(self):
        return Addon.objects.get(id=337141)

    def enable_addon_contributions(self):
        self.webapp.wants_contributions = True
        self.webapp.paypal_id = 'somebody'
        self.webapp.save()

    def post(self, *args, **kw):
        d = dict(*args, **kw)
        eq_(self.client.post(self.url, d).status_code, 302)

    def check(self, **kw):
        addon = self.get_webapp()
        for k, v in kw.items():
            if k in ('the_reason', 'the_future'):
                eq_(getattr(getattr(addon, k), 'localized_string'), unicode(v))
            else:
                eq_(getattr(addon, k), v)


class TestProfileStatusBar(TestProfileBase):

    def setUp(self):
        super(TestProfileStatusBar, self).setUp()
        self.remove_url = self.webapp.get_dev_url('profile.remove')

    def test_nav_link(self):
        # Removed links to "Manage Developer Profile" in bug 742902.
        raise SkipTest
        r = self.client.get(self.url)
        eq_(pq(r.content)('#edit-addon-nav li.selected a').attr('href'),
            self.url)

    def test_no_status_bar(self):
        self.webapp.the_reason = self.webapp.the_future = None
        self.webapp.save()
        assert not pq(self.client.get(self.url).content)('#status-bar')

    def test_status_bar_no_contrib(self):
        self.webapp.the_reason = self.webapp.the_future = '...'
        self.webapp.wants_contributions = False
        self.webapp.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('#status-bar')
        eq_(doc('#status-bar button').text(), 'Remove Profile')

    def test_status_bar_with_contrib(self):
        self.webapp.the_reason = self.webapp.the_future = '...'
        self.webapp.wants_contributions = True
        self.webapp.paypal_id = 'xxx'
        self.webapp.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('#status-bar')
        eq_(doc('#status-bar button').text(), 'Remove Profile')

    def test_remove_profile(self):
        self.webapp.the_reason = self.webapp.the_future = '...'
        self.webapp.save()
        self.client.post(self.remove_url)
        addon = self.get_webapp()
        eq_(addon.the_reason, None)
        eq_(addon.the_future, None)
        eq_(addon.takes_contributions, False)
        eq_(addon.wants_contributions, False)

    def test_remove_profile_without_content(self):
        # See bug 624852
        self.webapp.the_reason = self.webapp.the_future = None
        self.webapp.save()
        self.client.post(self.remove_url)
        addon = self.get_webapp()
        eq_(addon.the_reason, None)
        eq_(addon.the_future, None)

    def test_remove_both(self):
        self.webapp.the_reason = self.webapp.the_future = '...'
        self.webapp.wants_contributions = True
        self.webapp.paypal_id = 'xxx'
        self.webapp.save()
        self.client.post(self.remove_url)
        addon = self.get_webapp()
        eq_(addon.the_reason, None)
        eq_(addon.the_future, None)
        eq_(addon.takes_contributions, False)
        eq_(addon.wants_contributions, False)


class TestProfile(TestProfileBase):

    def test_without_contributions_labels(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('label[for=the_reason] .optional').length, 1)
        eq_(doc('label[for=the_future] .optional').length, 1)

    def test_without_contributions_fields_optional(self):
        self.post(the_reason='', the_future='')
        self.check(the_reason='', the_future='')

        self.post(the_reason='to be cool', the_future='')
        self.check(the_reason='to be cool', the_future='')

        self.post(the_reason='', the_future='hot stuff')
        self.check(the_reason='', the_future='hot stuff')

        self.post(the_reason='to be hot', the_future='cold stuff')
        self.check(the_reason='to be hot', the_future='cold stuff')

    def test_log(self):
        self.enable_addon_contributions()
        d = dict(the_reason='because', the_future='i can')
        o = ActivityLog.objects
        eq_(o.count(), 0)
        self.client.post(self.url, d)
        eq_(o.filter(action=amo.LOG.EDIT_PROPERTIES.id).count(), 1)

    def test_with_contributions_fields_required(self):
        self.enable_addon_contributions()

        d = dict(the_reason='', the_future='')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'profile_form', 'the_reason',
                             'This field is required.')
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')

        d = dict(the_reason='to be cool', the_future='')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')

        d = dict(the_reason='', the_future='hot stuff')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'profile_form', 'the_reason',
                             'This field is required.')

        self.post(the_reason='to be hot', the_future='cold stuff')
        self.check(the_reason='to be hot', the_future='cold stuff')


class TestResumeStep(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = self.get_addon()
        self.url = reverse('submit.app.resume', args=[self.webapp.app_slug])
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')

    def get_addon(self):
        return Addon.objects.no_cache().get(pk=337141)

    def test_no_step_redirect(self):
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, self.get_addon().get_dev_url('edit'), 302)

    def test_step_redirects(self):
        AppSubmissionChecklist.objects.create(addon=self.webapp,
                                              terms=True, manifest=True)
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, reverse('submit.app.details',
                                        args=[self.webapp.app_slug]))

    def test_redirect_from_other_pages(self):
        AppSubmissionChecklist.objects.create(addon=self.webapp,
                                              terms=True, manifest=True,
                                              details=True)
        r = self.client.get(self.webapp.get_dev_url('edit'), follow=True)
        self.assertRedirects(r, reverse('submit.app.payments',
                                        args=[self.webapp.app_slug]))

    def test_resume_without_checklist(self):
        r = self.client.get(reverse('submit.app.details',
                                    args=[self.webapp.app_slug]))
        eq_(r.status_code, 200)


class TestUpload(BaseUploadTest):
    fixtures = ['base/apps', 'base/users']

    def setUp(self):
        super(TestUpload, self).setUp()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.url = reverse('mkt.developers.upload')

    def post(self):
        # Has to be a binary, non xpi file.
        data = open(get_image_path('animated.png'), 'rb')
        return self.client.post(self.url, {'upload': data})

    def test_login_required(self):
        self.skip_if_disabled(settings.REGION_STORES)
        self.client.logout()
        r = self.post()
        eq_(r.status_code, 302)

    def test_create_fileupload(self):
        self.post()

        upload = FileUpload.objects.get(name='animated.png')
        eq_(upload.name, 'animated.png')
        data = open(get_image_path('animated.png'), 'rb').read()
        eq_(storage.open(upload.path).read(), data)

    def test_fileupload_user(self):
        self.client.login(username='regular@mozilla.com', password='password')
        self.post()
        user = UserProfile.objects.get(email='regular@mozilla.com')
        eq_(FileUpload.objects.get().user, user)

    def test_fileupload_ascii_post(self):
        path = 'apps/files/fixtures/files/jétpack.xpi'
        data = open(os.path.join(settings.ROOT, path))

        r = self.client.post(self.url, {'upload': data})
        # If this is broke, we'll get a traceback.
        eq_(r.status_code, 302)

    @attr('validator')
    def test_fileupload_validation(self):
        self.post()
        fu = FileUpload.objects.get(name='animated.png')
        assert_no_validation_errors(fu)
        assert fu.validation
        validation = json.loads(fu.validation)

        eq_(validation['success'], False)
        # The current interface depends on this JSON structure:
        eq_(validation['errors'], 1)
        eq_(validation['warnings'], 0)
        assert len(validation['messages'])
        msg = validation['messages'][0]
        assert 'uid' in msg, "Unexpected: %r" % msg
        eq_(msg['type'], u'error')
        eq_(msg['message'], u'JSON Parse Error')
        eq_(msg['description'], u'The webapp extension could not be parsed'
                                u' due to a syntax error in the JSON.')

    def test_redirect(self):
        r = self.post()
        upload = FileUpload.objects.get()
        url = reverse('mkt.developers.upload_detail', args=[upload.pk, 'json'])
        self.assertRedirects(r, url)


class TestUploadDetail(BaseUploadTest):
    fixtures = ['base/apps', 'base/appversion', 'base/users']

    def setUp(self):
        super(TestUploadDetail, self).setUp()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def post(self):
        # Has to be a binary, non xpi file.
        data = open(get_image_path('animated.png'), 'rb')
        return self.client.post(reverse('mkt.developers.upload'),
                                {'upload': data})

    def validation_ok(self):
        return {
            'errors': 0,
            'success': True,
            'warnings': 0,
            'notices': 0,
            'message_tree': {},
            'messages': [],
            'rejected': False,
            'metadata': {}}

    def upload_file(self, name):
        with self.file(name) as f:
            r = self.client.post(reverse('mkt.developers.upload'),
                                 {'upload': f})
        eq_(r.status_code, 302)

    def file_content(self, name):
        with self.file(name) as fp:
            return fp.read()

    @contextmanager
    def file(self, name):
        fn = os.path.join(settings.ROOT, 'mkt', 'developers', 'tests',
                          'addons', name)
        with open(fn, 'rb') as fp:
            yield fp

    @attr('validator')
    def test_detail_json(self):
        self.post()

        upload = FileUpload.objects.get()
        r = self.client.get(reverse('mkt.developers.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert_no_validation_errors(data)
        eq_(data['url'],
            reverse('mkt.developers.upload_detail', args=[upload.uuid,
                                                          'json']))
        eq_(data['full_report_url'],
            reverse('mkt.developers.upload_detail', args=[upload.uuid]))
        # We must have tiers
        assert len(data['validation']['messages'])
        msg = data['validation']['messages'][0]
        eq_(msg['tier'], 1)

    @mock.patch('mkt.developers.tasks.urllib2.urlopen')
    @mock.patch('mkt.developers.tasks.run_validator')
    def test_detail_for_free_extension_webapp(self, validator_mock,
                                              urlopen_mock):
        rs = mock.Mock()
        rs.read.return_value = self.file_content('mozball.owa')
        urlopen_mock.return_value = rs
        validator_mock.return_value = json.dumps(self.validation_ok())
        self.upload_file('mozball.owa')
        upload = FileUpload.objects.get()
        tasks.fetch_manifest('http://xx.com/manifest.owa', upload.pk)

        r = self.client.get(reverse('mkt.developers.upload_detail',
                                    args=[upload.uuid, 'json']))
        data = json.loads(r.content)
        eq_(data['validation']['messages'], [])  # no errors
        assert_no_validation_errors(data)  # no exception
        eq_(r.status_code, 200)
        eq_(data['url'],
            reverse('mkt.developers.upload_detail', args=[upload.uuid,
                                                          'json']))
        eq_(data['full_report_url'],
            reverse('mkt.developers.upload_detail', args=[upload.uuid]))

    def test_detail_view(self):
        self.post()
        upload = FileUpload.objects.get(name='animated.png')
        r = self.client.get(reverse('mkt.developers.upload_detail',
                                    args=[upload.uuid]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('header h1').text(), 'Validation Results for animated.png')
        suite = doc('#addon-validator-suite')
        eq_(suite.attr('data-validateurl'),
            reverse('mkt.developers.standalone_upload_detail',
                    args=[upload.uuid]))
        eq_(suite('#suite-results-tier-2').length, 1)


def assert_json_error(request, field, msg):
    eq_(request.status_code, 400)
    eq_(request['Content-Type'], 'application/json')
    field = '__all__' if field is None else field
    content = json.loads(request.content)
    assert field in content, '%r not in %r' % (field, content)
    eq_(content[field], [msg])


def assert_json_field(request, field, msg):
    eq_(request.status_code, 200)
    eq_(request['Content-Type'], 'application/json')
    content = json.loads(request.content)
    assert field in content, '%r not in %r' % (field, content)
    eq_(content[field], msg)


class TestDeleteApp(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Webapp.objects.get(id=337141)
        self.url = self.webapp.get_dev_url('delete')
        self.versions_url = self.webapp.get_dev_url('versions')
        self.dev_url = reverse('mkt.developers.apps')
        self.client.login(username='admin@mozilla.com', password='password')
        waffle.models.Switch.objects.create(name='soft_delete', active=True)

    def test_delete_nonincomplete(self):
        r = self.client.post(self.url)
        self.assertRedirects(r, self.dev_url)
        eq_(Addon.objects.count(), 0, 'App should have been deleted.')

    def test_delete_incomplete(self):
        self.webapp.update(status=amo.STATUS_NULL)
        r = self.client.post(self.url)
        self.assertRedirects(r, self.dev_url)
        eq_(Addon.objects.count(), 0, 'App should have been deleted.')

    def test_delete_incomplete_manually(self):
        webapp = amo.tests.addon_factory(type=amo.ADDON_WEBAPP, name='Boop',
                                         status=amo.STATUS_NULL)
        eq_(list(Webapp.objects.filter(id=webapp.id)), [webapp])
        webapp.delete('POOF!')
        eq_(list(Webapp.objects.filter(id=webapp.id)), [],
            'App should have been deleted.')

    def check_delete_redirect(self, src, dst):
        r = self.client.post(urlparams(self.url, to=src))
        self.assertRedirects(r, dst)
        eq_(Addon.objects.count(), 0, 'App should have been deleted.')

    def test_delete_redirect_to_dashboard(self):
        self.check_delete_redirect(self.dev_url, self.dev_url)

    def test_delete_redirect_to_dashboard_with_qs(self):
        url = self.dev_url + '?sort=created'
        self.check_delete_redirect(url, url)

    def test_form_action_on_status_page(self):
        # If we started on app's Manage Status page, upon deletion we should
        # be redirecte to the Dashboard.
        r = self.client.get(self.versions_url)
        eq_(pq(r.content)('.modal-delete form').attr('action'), self.url)
        self.check_delete_redirect('', self.dev_url)


class TestRemoveLocale(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Addon.objects.no_cache().get(id=337141)
        self.url = self.webapp.get_dev_url('remove-locale')
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')

    def test_bad_request(self):
        r = self.client.post(self.url)
        eq_(r.status_code, 400)

    def test_success(self):
        self.webapp.name = {'en-US': 'woo', 'el': 'yeah'}
        self.webapp.save()
        self.webapp.remove_locale('el')
        r = self.client.post(self.url, {'locale': 'el'})
        eq_(r.status_code, 200)
        qs = list(Translation.objects.filter(localized_string__isnull=False)
                  .values_list('locale', flat=True)
                  .filter(id=self.webapp.name_id))
        eq_(qs, ['en-US'])

    def test_delete_default_locale(self):
        r = self.client.post(self.url, {'locale': self.webapp.default_locale})
        eq_(r.status_code, 400)


class TestTerms(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.user = self.get_user()
        self.client.login(username=self.user.email, password='password')
        self.url = reverse('mkt.developers.apps.terms')

    def get_user(self):
        return UserProfile.objects.get(email='regular@mozilla.com')

    def test_login_required(self):
        self.client.logout()
        self.assertLoginRequired(self.client.get(self.url))

    def test_accepted(self):
        self.user.update(read_dev_agreement=datetime.datetime.now())
        res = self.client.get(self.url)
        doc = pq(res.content)
        eq_(doc('#dev-agreement').length, 1)
        eq_(doc('#agreement-form').length, 0)

    def test_not_accepted(self):
        self.user.update(read_dev_agreement=None)
        res = self.client.get(self.url)
        doc = pq(res.content)
        eq_(doc('#dev-agreement').length, 1)
        eq_(doc('#agreement-form').length, 1)

    def test_accept(self):
        self.user.update(read_dev_agreement=None)
        res = self.client.post(self.url, {'read_dev_agreement': 'yeah'})
        eq_(res.status_code, 200)
        assert self.get_user().read_dev_agreement
