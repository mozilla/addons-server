# -*- coding: utf-8 -*-
from contextlib import contextmanager
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core import mail
from django.utils.http import urlencode

import mock
from nose.plugins.attrib import attr
from nose.plugins.skip import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle
# Unused, but needed so that we can patch jingo.
from waffle import helpers

import amo
import amo.tests
import paypal
from paypal.check import Check
from amo.helpers import babel_datetime, timesince
from amo.tests import assert_no_validation_errors, close_to_now
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from addons.models import Addon, AddonUpsell, AddonUser, Charity
from browse.tests import test_listing_sort, test_default_sort
from mkt.developers.models import ActivityLog
from mkt.submit.models import AppSubmissionChecklist
from mkt.developers import tasks
from files.models import File, FileUpload
from files.tests.test_models import UploadTest as BaseUploadTest
from market.models import AddonPremium, Price, Refund
from reviews.models import Review
from stats.models import Contribution
from translations.models import Translation
from users.models import UserProfile
from versions.models import Version
from webapps.models import Webapp


class MetaTests(amo.tests.TestCase):

    def test_assert_close_to_now(dt):
        assert close_to_now(datetime.now() - timedelta(seconds=30))
        assert not close_to_now(datetime.now() + timedelta(days=30))
        assert not close_to_now(datetime.now() + timedelta(minutes=3))
        assert not close_to_now(datetime.now() + timedelta(seconds=30))


class HubTest(amo.tests.TestCase):
    fixtures = ['browse/nameless-addon', 'base/users']

    def setUp(self):
        self.url = reverse('mkt.developers.apps')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        eq_(self.client.get(self.url).status_code, 200)
        self.user_profile = UserProfile.objects.get(id=999)

    def clone_addon(self, num, addon_id=57132):
        ids = []
        for i in range(num):
            addon = Addon.objects.get(id=addon_id)
            data = dict(type=addon.type, status=addon.status,
                        name='cloned-addon-%s-%s' % (addon_id, i))
            new_addon = Addon.objects.create(**data)
            AddonUser.objects.create(user=self.user_profile, addon=new_addon)
            ids.append(new_addon.id)
        return ids


class AppHubTest(HubTest):
    fixtures = ['webapps/337141-steamcube', 'base/users']


class TestHome(HubTest):

    def test_legacy_login_redirect(self):
        self.client.logout()
        r = self.client.get('/en-US/firefox/users/login')
        got, exp = r['Location'], '/en-US/users/login'
        assert got.endswith(exp), 'Expected %s. Got %s.' % (exp, got)
        r = self.client.get('/en-US/users/login')
        got, exp = r['Location'], '/en-US/login'
        assert got.endswith(exp), 'Expected %s. Got %s.' % (exp, got)

    def test_login_redirect(self):
        self.client.logout()
        r = self.client.get(self.url)
        self.assertLoginRedirects(r, '/en-US/developers/submissions', 302)

    def test_home(self):
        for url in [self.url, reverse('home')]:
            r = self.client.get(url, follow=True)
            eq_(r.status_code, 200)
            self.assertTemplateUsed(r, 'developers/addons/dashboard.html')


class Test404(amo.tests.TestCase):

    def test_404_devhub(self):
        response = self.client.get('/xxx', follow=True)
        eq_(response.status_code, 404)
        self.assertTemplateUsed(response, 'site/404.html')


class TestAppBreadcrumbs(AppHubTest):

    def setUp(self):
        super(TestAppBreadcrumbs, self).setUp()
        waffle.models.Flag.objects.create(name='accept-webapps', everyone=True)

    def test_regular_breadcrumbs(self):
        r = self.client.get(reverse('submit.app'), follow=True)
        eq_(r.status_code, 200)
        expected = [
            ('My Submissions', reverse('mkt.developers.apps')),
            ('Submit App', None),
        ]
        amo.tests.check_links(expected, pq(r.content)('#breadcrumbs li'))

    def test_webapp_management_breadcrumbs(self):
        webapp = Webapp.objects.get(id=337141)
        AddonUser.objects.create(user=self.user_profile, addon=webapp)
        r = self.client.get(webapp.get_dev_url('edit'))
        eq_(r.status_code, 200)
        expected = [
            ('My Submissions', reverse('mkt.developers.apps')),
            (unicode(webapp.name), None),
        ]
        amo.tests.check_links(expected, pq(r.content)('#breadcrumbs li'))


class TestAppDashboard(AppHubTest):

    def setUp(self):
        super(TestAppDashboard, self).setUp()
        self.url = reverse('mkt.developers.apps')
        waffle.models.Flag.objects.create(name='accept-webapps', everyone=True)

    def get_app(self):
        return Addon.objects.get(id=337141)

    def test_no_apps(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#dashboard .item').length, 0)

    def test_public_app(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        app = self.get_app()
        AddonUser.objects.create(addon=app, user=self.user_profile)
        doc = pq(self.client.get(self.url).content)
        item = doc('.item[data-addonid=%s]' % app.id)
        assert item.find('.price'), 'Expected price'
        assert item.find('.item-details'), 'Expected item details'
        assert not item.find('p.incomplete'), (
            'Unexpected message about incomplete add-on')

    def test_incomplete_app(self):
        AddonUser.objects.create(addon_id=337141, user_id=self.user_profile.id)
        app = self.get_app()
        app.update(status=amo.STATUS_NULL)
        doc = pq(self.client.get(self.url).content)
        assert doc('.item[data-addonid=%s] p.incomplete' % app.id), (
            'Expected message about incompleted add-on')


class TestAppDashboardSorting(AppHubTest):

    def setUp(self):
        super(TestAppDashboardSorting, self).setUp()
        self.clone_addon(3, addon_id=337141)
        self.my_apps = self.user_profile.addons
        self.url = reverse('mkt.developers.apps')
        waffle.models.Flag.objects.create(name='accept-webapps', everyone=True)

    def test_pagination(self):
        doc = pq(self.client.get(self.url).content)('#dashboard')
        eq_(doc('.item').length, 3)
        eq_(doc('#sorter').length, 1)
        eq_(doc('.paginator').length, 0)

        # We want more than 10 apps so that the paginator shows up.
        self.clone_addon(8, addon_id=337141)
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


class TestDevRequired(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.get_url = self.addon.get_dev_url('payments')
        self.post_url = self.addon.get_dev_url('payments.disable')
        assert self.client.login(username='del@icio.us', password='password')
        self.au = AddonUser.objects.get(user__email='del@icio.us',
                                        addon=self.addon)
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
        self.addon.update(status=amo.STATUS_DISABLED)
        eq_(self.client.post(self.get_url).status_code, 403)

    def test_disabled_post_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.assertRedirects(self.client.post(self.post_url), self.get_url)


class TestVersionStats(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def test_counts(self):
        addon = Addon.objects.get(id=3615)
        version = addon.current_version
        user = UserProfile.objects.get(email='admin@mozilla.com')
        for _ in range(10):
            Review.objects.create(addon=addon, user=user,
                                  version=addon.current_version)

        url = reverse('mkt.developers.versions.stats', args=[addon.slug])
        r = json.loads(self.client.get(url).content)
        exp = {str(version.id):
               {'reviews': 10, 'files': 1, 'version': version.version,
                'id': version.id}}
        self.assertDictEqual(r, exp)


class TestEditPayments(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = self.get_addon()
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        self.foundation = Charity.objects.create(
            id=amo.FOUNDATION_ORG, name='moz', url='$$.moz', paypal='moz.pal')
        self.url = self.addon.get_dev_url('payments')
        assert self.client.login(username='del@icio.us', password='password')
        self.paypal_mock = mock.Mock()
        self.paypal_mock.return_value = (True, None)
        paypal.check_paypal_id = self.paypal_mock

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def post(self, *args, **kw):
        d = dict(*args, **kw)
        eq_(self.client.post(self.url, d).status_code, 302)

    def check(self, **kw):
        addon = self.get_addon()
        for k, v in kw.items():
            eq_(getattr(addon, k), v)
        assert addon.wants_contributions
        assert addon.takes_contributions

    def test_dev_paypal_id_length(self):
        raise SkipTest
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(int(doc('#id_paypal_id').attr('size')), 50)

    def test_no_future(self):
        raise SkipTest
        self.get_addon().update(the_future=None)
        res = self.client.get(self.url)
        err = pq(res.content)('p.error').text()
        eq_('completed developer profile' in err, True)

    def test_with_upsell_no_contributions(self):
        raise SkipTest
        AddonUpsell.objects.create(free=self.addon, premium=self.addon)
        res = self.client.get(self.url)
        error = pq(res.content)('p.error').text()
        eq_('premium add-on enrolled' in error, True)
        eq_(' %s' % self.addon.name in error, True)

    @mock.patch('addons.models.Addon.upsell')
    def test_upsell(self, upsell):
        upsell.return_value = self.get_addon()
        d = dict(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                 annoying=amo.CONTRIB_AFTER, premium_type=amo.ADDON_PREMIUM)
        res = self.client.post(self.url, d)
        eq_('premium add-on' in res.content, True)


class TestPaymentsProfile(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

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


class MarketplaceMixin(object):
    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.addon.update(status=amo.STATUS_NOMINATED,
                          highest_status=amo.STATUS_NOMINATED)
        self.url = self.addon.get_dev_url('payments')
        assert self.client.login(username='del@icio.us', password='password')

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
        self.other_addon = Addon.objects.create(type=amo.ADDON_EXTENSION,
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
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def get_data(self):
        return {
            'price': self.price.pk,
            'free': self.other_addon.pk,
            'do_upsell': 1,
            'text': 'some upsell',
            'premium_type': amo.ADDON_PREMIUM,
            'support_email': 'c@c.com',
        }

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
        self.other_addon.update(type=amo.ADDON_WEBAPP)
        res = self.client.post(self.url, data=self.get_data())
        eq_(res.status_code, 200)
        eq_(len(res.context['form'].errors['free']), 1)
        eq_(len(self.addon._upsell_to.all()), 0)

    def test_set_upsell_required(self):
        self.setup_premium()
        data = self.get_data()
        data['text'] = ''
        res = self.client.post(self.url, data=data)
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
        data = self.get_data().copy()
        data['do_upsell'] = 0
        self.client.post(self.url, data=data)
        eq_(len(self.addon._upsell_to.all()), 0)

    def test_change_upsell(self):
        self.setup_premium()
        AddonUpsell.objects.create(free=self.other_addon,
                                   premium=self.addon, text='foo')
        eq_(self.addon._upsell_to.all()[0].text, 'foo')
        data = self.get_data().copy()
        data['text'] = 'bar'
        self.client.post(self.url, data=data)
        eq_(self.addon._upsell_to.all()[0].text, 'bar')

    def test_replace_upsell(self):
        self.setup_premium()
        # Make this add-on an upsell of some free add-on.
        AddonUpsell.objects.create(free=self.other_addon,
                                   premium=self.addon, text='foo')
        # And this will become our new upsell, replacing the one above.
        new = Addon.objects.create(type=amo.ADDON_EXTENSION,
                                   premium_type=amo.ADDON_FREE)
        new.update(status=amo.STATUS_PUBLIC)
        AddonUser.objects.create(addon=new, user=self.addon.authors.all()[0])

        eq_(self.addon._upsell_to.all()[0].text, 'foo')
        data = self.get_data().copy()
        data.update(free=new.id, text='bar')
        self.client.post(self.url, data=data)
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
    @mock.patch('paypal.get_personal_data', lambda x: {})
    def test_permissions_token(self):
        self.setup_premium()
        eq_(self.addon.premium.paypal_permissions_token, '')
        url = self.addon.get_dev_url('acquire_refund_permission')
        data = {'request_token': 'foo', 'verification_code': 'bar'}
        self.client.get('%s?%s' % (url, urlencode(data)))
        self.addon = Addon.objects.get(pk=self.addon.pk)
        eq_(self.addon.premium.paypal_permissions_token, 'FOO')


class TestIssueRefund(amo.tests.TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        waffle.models.Switch.objects.create(name='allow-refund', active=True)

        Addon.objects.get(id=3615).update(type=amo.ADDON_WEBAPP,
                                          app_slug='ballin')
        self.addon = Addon.objects.no_cache().get(id=3615)
        self.transaction_id = u'fake-txn-id'
        self.paykey = u'fake-paykey'
        self.client.login(username='del@icio.us', password='password')
        self.user = UserProfile.objects.get(username='clouserw')
        self.url = self.addon.get_dev_url('issue_refund')

    def make_purchase(self, uuid='123456', type=amo.CONTRIB_PURCHASE):
        return Contribution.objects.create(uuid=uuid, addon=self.addon,
                                           transaction_id=self.transaction_id,
                                           user=self.user, paykey=self.paykey,
                                           amount=Decimal('10'), type=type)

    def test_request_issue(self):
        c = self.make_purchase()
        r = self.client.get(self.url, {'transaction_id': c.transaction_id})
        doc = pq(r.content)
        eq_(doc('#issue-refund button').length, 2)
        eq_(doc('#issue-refund input[name=transaction_id]').val(),
            self.transaction_id)

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


class TestRefunds(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        waffle.models.Switch.objects.create(name='allow-refund', active=True)
        self.addon = Addon.objects.get(id=3615)
        self.addon.premium_type = amo.ADDON_PREMIUM
        self.addon.save()
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.url = self.addon.get_dev_url('refunds')
        self.client.login(username='del@icio.us', password='password')
        self.queues = {
            'pending': amo.REFUND_PENDING,
            'approved': amo.REFUND_APPROVED,
            'instant': amo.REFUND_APPROVED_INSTANT,
            'declined': amo.REFUND_DECLINED,
        }

    def generate_refunds(self):
        self.expected = {}
        for status in amo.REFUND_STATUSES.keys():
            for x in xrange(status + 1):
                c = Contribution.objects.create(addon=self.addon,
                    user=self.user, type=amo.CONTRIB_PURCHASE)
                r = Refund.objects.create(contribution=c, status=status)
                self.expected.setdefault(status, []).append(r)

    def test_anonymous(self):
        self.client.logout()
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r,
            '%s?to=%s' % (reverse('users.login'), self.url))

    def test_bad_owner(self):
        self.client.logout()
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.get(self.url)
        eq_(r.status_code, 403)

    def test_owner(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_admin(self):
        self.client.logout()
        self.client.login(username='admin@mozilla.com', password='password')
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_not_premium(self):
        self.addon.premium_type = amo.ADDON_FREE
        self.addon.save()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#enable-payments').length, 1)

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
            eq_(list(r.context[key]), list(self.expected[status]))

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
        others = Refund.objects.exclude(status=amo.REFUND_PENDING)
        for refund in others:
            tr = table.find('.refund[data-refundid=%s]' % refund.id)
            eq_(tr.find('.purchased-date').text(),
                babel_datetime(refund.contribution.created).strip())
            eq_(tr.find('.requested-date').text(),
                babel_datetime(refund.requested).strip())


class TestDelete(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.addon = self.get_addon()
        self.addon.update(type=amo.ADDON_WEBAPP, app_slug='ballin')
        assert self.client.login(username='del@icio.us', password='password')
        self.url = self.addon.get_dev_url('delete')

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def test_post_not(self):
        # Update this test when BrowserID re-auth is available.
        raise SkipTest()
        r = self.client.post(self.url, follow=True)
        eq_(pq(r.content)('.notification-box').text(),
                          'Password was incorrect. App was not deleted.')

    def test_post(self):
        waffle.models.Switch.objects.create(name='soft_delete', active=True)
        r = self.client.post(self.url, follow=True)
        eq_(pq(r.content)('.notification-box').text(), 'App deleted.')
        self.assertRaises(Addon.DoesNotExist, self.get_addon)


class TestProfileBase(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.url = self.addon.get_dev_url('profile')
        assert self.client.login(username='del@icio.us', password='password')

    def get_addon(self):
        return Addon.objects.no_cache().get(id=self.addon.id)

    def enable_addon_contributions(self):
        self.addon.wants_contributions = True
        self.addon.paypal_id = 'somebody'
        self.addon.save()

    def post(self, *args, **kw):
        d = dict(*args, **kw)
        eq_(self.client.post(self.url, d).status_code, 302)

    def check(self, **kw):
        addon = self.get_addon()
        for k, v in kw.items():
            if k in ('the_reason', 'the_future'):
                eq_(getattr(getattr(addon, k), 'localized_string'), unicode(v))
            else:
                eq_(getattr(addon, k), v)


class TestProfileStatusBar(TestProfileBase):

    def setUp(self):
        super(TestProfileStatusBar, self).setUp()
        self.remove_url = self.addon.get_dev_url('profile.remove')

    def test_no_status_bar(self):
        self.addon.the_reason = self.addon.the_future = None
        self.addon.save()
        assert not pq(self.client.get(self.url).content)('#status-bar')

    def test_status_bar_no_contrib(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.wants_contributions = False
        self.addon.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('#status-bar')
        eq_(doc('#status-bar button').text(), 'Remove Profile')

    def test_status_bar_with_contrib(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.wants_contributions = True
        self.addon.paypal_id = 'xxx'
        self.addon.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('#status-bar')
        eq_(doc('#status-bar button').text(), 'Remove Profile')

    def test_remove_profile(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        self.client.post(self.remove_url)
        addon = self.get_addon()
        eq_(addon.the_reason, None)
        eq_(addon.the_future, None)
        eq_(addon.takes_contributions, False)
        eq_(addon.wants_contributions, False)

    def test_remove_profile_without_content(self):
        # See bug 624852
        self.addon.the_reason = self.addon.the_future = None
        self.addon.save()
        self.client.post(self.remove_url)
        addon = self.get_addon()
        eq_(addon.the_reason, None)
        eq_(addon.the_future, None)

    def test_remove_both(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.wants_contributions = True
        self.addon.paypal_id = 'xxx'
        self.addon.save()
        self.client.post(self.remove_url)
        addon = self.get_addon()
        eq_(addon.the_reason, None)
        eq_(addon.the_future, None)
        eq_(addon.takes_contributions, False)
        eq_(addon.wants_contributions, False)


class TestProfile(TestProfileBase):

    def test_without_contributions_labels(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(r.context['webapp'], False)
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


class TestAppProfile(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.webapp = Addon.objects.get(id=337141)
        self.url = self.webapp.get_dev_url('profile')

    def test_nav_link(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('#edit-addon-nav li.selected a').attr('href'),
            self.url)

    def test_labels(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(r.context['webapp'], True)
        doc = pq(r.content)
        eq_(doc('label[for=the_reason] .optional').length, 1)
        eq_(doc('label[for=the_future] .optional').length, 1)


class TestResumeStep(amo.tests.TestCase):

    fixtures = ['base/addon_3615', 'base/addon_5579', 'base/users']

    def get_addon(self):
        return Addon.objects.no_cache().get(pk=3615)

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.get_addon().update(type=amo.ADDON_WEBAPP, app_slug='a3615')
        self.addon = self.get_addon()
        self.url = reverse('submit.app.resume', args=['a3615'])

    def test_no_step_redirect(self):
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, self.get_addon().get_dev_url('edit'), 302)

    def test_step_redirects(self):
        AppSubmissionChecklist.objects.create(addon=self.get_addon(),
                                              terms=True, manifest=True)
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, reverse('submit.app.details',
                                        args=['a3615']))

    def test_redirect_from_other_pages(self):
        AppSubmissionChecklist.objects.create(addon=self.get_addon(),
                                              terms=True, manifest=True,
                                              details=True)
        r = self.client.get(reverse('mkt.developers.addons.edit',
                                    args=['a3615']), follow=True)
        self.assertRedirects(r, reverse('submit.app.payments',
                                        args=['a3615']))

    def test_resume_without_checklist(self):
        r = self.client.get(reverse('submit.app.details', args=['a3615']))
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
        self.client.logout()
        r = self.post()
        eq_(r.status_code, 302)

    def test_create_fileupload(self):
        self.post()

        upload = FileUpload.objects.get(name='animated.png')
        eq_(upload.name, 'animated.png')
        data = open(get_image_path('animated.png'), 'rb').read()
        eq_(open(upload.path).read(), data)

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
        eq_(msg['message'], u'The package is not of a recognized type.')
        eq_(msg['description'], u'')

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
        waffle.models.Flag.objects.create(name='form-errors-in-validation',
                                          everyone=True)
        rs = mock.Mock()
        rs.read.return_value = self.file_content('mozball.owa')
        rs.headers = {'Content-Type': 'application/x-web-app-manifest+json'}
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

    @mock.patch('mkt.developers.tasks.run_validator')
    def check_excluded_platforms(self, xpi, platforms, v):
        v.return_value = json.dumps(self.validation_ok())
        self.upload_file(xpi)
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('mkt.developers.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        eq_(sorted(data['platforms_to_exclude']), sorted(platforms))

    def test_multi_app_addon_can_have_all_platforms(self):
        self.check_excluded_platforms('mobile-2.9.10-fx+fn.xpi', [])

    def test_mobile_excludes_desktop_platforms(self):
        self.check_excluded_platforms('mobile-0.1-fn.xpi',
            [str(p) for p in amo.DESKTOP_PLATFORMS])

    def test_android_excludes_desktop_platforms(self):
        # Test native Fennec.
        self.check_excluded_platforms('android-phone.xpi',
            [str(p) for p in amo.DESKTOP_PLATFORMS])

    def test_search_tool_excludes_all_platforms(self):
        self.check_excluded_platforms('searchgeek-20090701.xml',
            [str(p) for p in amo.SUPPORTED_PLATFORMS])

    def test_desktop_excludes_mobile(self):
        self.check_excluded_platforms('desktop.xpi',
            [str(p) for p in amo.MOBILE_PLATFORMS])

    @mock.patch('mkt.developers.tasks.run_validator')
    @mock.patch.object(waffle, 'flag_is_active')
    def test_unparsable_xpi(self, flag_is_active, v):
        flag_is_active.return_value = True
        v.return_value = json.dumps(self.validation_ok())
        self.upload_file('unopenable.xpi')
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('mkt.developers.upload_detail',
                                    args=[upload.uuid, 'json']))
        data = json.loads(r.content)
        eq_(list(m['message'] for m in data['validation']['messages']),
            [u'Could not parse install.rdf.'])


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


class BaseWebAppTest(BaseUploadTest, amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/platforms']

    def setUp(self):
        super(BaseWebAppTest, self).setUp()
        waffle.models.Flag.objects.create(name='accept-webapps', everyone=True)
        self.manifest = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                                     'addons', 'mozball.webapp')
        self.upload = self.get_upload(abspath=self.manifest)
        self.url = reverse('submit.app.manifest')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.client.post(reverse('submit.app.terms'),
                         {'read_dev_agreement': True})

    def post(self, desktop_platforms=[amo.PLATFORM_ALL], mobile_platforms=[],
             expect_errors=False):
        d = dict(upload=self.upload.pk,
                 desktop_platforms=[p.id for p in desktop_platforms],
                 mobile_platforms=[p.id for p in mobile_platforms])
        r = self.client.post(self.url, d, follow=True)
        eq_(r.status_code, 200)
        if not expect_errors:
            # Show any unexpected form errors.
            if r.context and 'new_addon_form' in r.context:
                eq_(r.context['new_addon_form'].errors.as_text(), '')
        return r

    def post_addon(self):
        eq_(Addon.objects.count(), 0)
        self.post()
        return Addon.objects.get()


class TestCreateWebApp(BaseWebAppTest):

    def test_page_title(self):
        eq_(pq(self.client.get(self.url).content)('title').text(),
            'App Manifest | Developer Hub | Mozilla Marketplace')

    def test_post_app_redirect(self):
        r = self.post()
        addon = Addon.objects.get()
        self.assertRedirects(r, reverse('submit.app.details',
                                        args=[addon.app_slug]))

    def test_addon_from_uploaded_manifest(self):
        addon = self.post_addon()
        eq_(addon.type, amo.ADDON_WEBAPP)
        eq_(addon.guid, None)
        eq_(unicode(addon.name), 'MozillaBall')
        eq_(addon.slug, 'app-%s' % addon.id)
        eq_(addon.app_slug, 'mozillaball')
        eq_(addon.summary, u'Exciting Open Web development action!')
        eq_(Translation.objects.get(id=addon.summary.id, locale='it'),
            u'Azione aperta emozionante di sviluppo di fotoricettore!')

    def test_version_from_uploaded_manifest(self):
        addon = self.post_addon()
        eq_(addon.current_version.version, '1.0')

    def test_file_from_uploaded_manifest(self):
        addon = self.post_addon()
        files = addon.current_version.files.all()
        eq_(len(files), 1)
        eq_(files[0].status, amo.STATUS_PUBLIC)


class TestDeleteApp(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Webapp.objects.get(id=337141)
        self.url = self.webapp.get_dev_url('delete')
        self.versions_url = self.webapp.get_dev_url('versions')
        self.dev_url = reverse('mkt.developers.apps')
        self.client.login(username='admin@mozilla.com', password='password')
        waffle.models.Flag.objects.create(name='accept-webapps', everyone=True)
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


class TestRequestReview(amo.tests.TestCase):
    fixtures = ['base/users', 'base/platforms']

    def setUp(self):
        self.addon = Addon.objects.create(type=1, name='xxx')
        self.version = Version.objects.create(addon=self.addon)
        self.file = File.objects.create(version=self.version,
                                        platform_id=amo.PLATFORM_ALL.id)
        self.redirect_url = self.addon.get_dev_url('versions')
        self.lite_url = reverse('mkt.developers.request-review',
                                args=[self.addon.slug, amo.STATUS_LITE])
        self.public_url = reverse('mkt.developers.request-review',
                                  args=[self.addon.slug, amo.STATUS_PUBLIC])
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def get_addon(self):
        return Addon.objects.get(id=self.addon.id)

    def get_version(self):
        return Version.objects.get(pk=self.version.id)

    def check(self, old_status, url, new_status):
        self.addon.update(status=old_status)
        r = self.client.post(url)
        self.assertRedirects(r, self.redirect_url)
        eq_(self.get_addon().status, new_status)

    def check_400(self, url):
        r = self.client.post(url)
        eq_(r.status_code, 400)

    def test_404(self):
        bad_url = self.public_url.replace(str(amo.STATUS_PUBLIC), '0')
        eq_(self.client.post(bad_url).status_code, 404)

    def test_public(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
        self.check_400(self.lite_url)
        self.check_400(self.public_url)

    def test_disabled_by_user_to_lite(self):
        self.addon.update(disabled_by_user=True)
        self.check_400(self.lite_url)

    def test_disabled_by_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        self.check_400(self.lite_url)

    def test_lite_to_lite(self):
        self.addon.update(status=amo.STATUS_LITE)
        self.check_400(self.lite_url)

    def test_lite_to_public(self):
        eq_(self.version.nomination, None)
        self.check(amo.STATUS_LITE, self.public_url,
                   amo.STATUS_LITE_AND_NOMINATED)
        assert close_to_now(self.get_version().nomination)

    def test_purgatory_to_lite(self):
        self.check(amo.STATUS_PURGATORY, self.lite_url, amo.STATUS_UNREVIEWED)

    def test_purgatory_to_public(self):
        eq_(self.version.nomination, None)
        self.check(amo.STATUS_PURGATORY, self.public_url,
                   amo.STATUS_NOMINATED)
        assert close_to_now(self.get_version().nomination)

    def test_lite_and_nominated_to_public(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.check_400(self.public_url)

    def test_lite_and_nominated(self):
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        self.check_400(self.lite_url)
        self.check_400(self.public_url)

    def test_renominate_for_full_review(self):
        # When a version is rejected, the addon is disabled.
        # The author must upload a new version and re-nominate.
        # However, renominating the *same* version does not adjust the
        # nomination date.
        orig_date = datetime.now() - timedelta(days=30)
        # Pretend it was nominated in the past:
        self.version.update(nomination=orig_date)
        self.check(amo.STATUS_NULL, self.public_url, amo.STATUS_NOMINATED)
        eq_(self.get_version().nomination.timetuple()[0:5],
            orig_date.timetuple()[0:5])

    def test_renomination_doesnt_reset_nomination_date(self):
        # Nominate:
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        # Pretend it was nominated in the past:
        orig_date = datetime.now() - timedelta(days=30)
        self.version.update(nomination=orig_date, _signal=False)
        # Reject it:
        self.addon.update(status=amo.STATUS_NULL)
        # Re-nominate:
        self.addon.update(status=amo.STATUS_LITE_AND_NOMINATED)
        eq_(self.get_version().nomination.timetuple()[0:5],
            orig_date.timetuple()[0:5])


class TestRemoveLocale(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        Addon.objects.get(id=3615).update(type=amo.ADDON_WEBAPP,
                                          app_slug='ballin')
        self.addon = Addon.objects.no_cache().get(id=3615)
        self.url = reverse('mkt.developers.remove-locale', args=['a3615'])
        assert self.client.login(username='del@icio.us', password='password')

    def test_bad_request(self):
        r = self.client.post(self.url)
        eq_(r.status_code, 400)

    def test_success(self):
        self.addon.name = {'en-US': 'woo', 'el': 'yeah'}
        self.addon.save()
        self.addon.remove_locale('el')
        qs = (Translation.objects.filter(localized_string__isnull=False)
              .values_list('locale', flat=True))
        r = self.client.post(self.url, {'locale': 'el'})
        eq_(r.status_code, 200)
        eq_(sorted(qs.filter(id=self.addon.name_id)), ['en-US'])

    def test_delete_default_locale(self):
        r = self.client.post(self.url, {'locale': self.addon.default_locale})
        eq_(r.status_code, 400)
