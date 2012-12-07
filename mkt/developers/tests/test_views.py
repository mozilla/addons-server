# -*- coding: utf-8 -*-
import datetime
import json
import os
import tempfile
from contextlib import contextmanager
from decimal import Decimal

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.core.files.uploadedfile import SimpleUploadedFile

from nose import SkipTest
import mock
import waffle
from dateutil.parser import parse as parse_dt
from nose.plugins.attrib import attr
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
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
from mkt.constants import MAX_PACKAGED_APP_SIZE
from mkt.developers import tasks
from mkt.developers.models import ActivityLog
from mkt.submit.models import AppSubmissionChecklist
from mkt.webapps.models import Webapp
from stats.models import Contribution
from translations.models import Translation
from users.models import UserProfile
from versions.models import Version


class AppHubTest(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.create_switch('allow-b2g-paid-submission')

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
        eq_(doc('.status-link').length, 1)
        eq_(doc('.more-actions-popup').length, 0)

    def test_incomplete_app(self):
        app = self.get_app()
        app.update(status=amo.STATUS_NULL)
        self.make_mine()
        doc = pq(self.client.get(self.url).content)
        assert doc('.item[data-addonid=%s] p.incomplete' % app.id), (
            'Expected message about incompleted add-on')
        eq_(doc('.more-actions-popup').length, 0)

    def test_packaged_version(self):
        app = self.get_app()
        version = Version.objects.create(addon=app, version='1.23')
        app.update(_current_version=version, is_packaged=True)
        self.make_mine()
        doc = pq(self.client.get(self.url).content)
        eq_(doc('.item[data-addonid=%s] .item-current-version' % app.id
                ).text(),
            'Packaged App Version: 1.23')

    @mock.patch('mkt.webapps.tasks.update_cached_manifests')
    def test_pending_version(self, ucm):
        ucm.return_value = True

        app = self.get_app()
        self.make_mine()
        app.update(is_packaged=True)
        Version.objects.create(addon=app, version='1.24')
        doc = pq(self.client.get(self.url).content)
        eq_(doc('.item[data-addonid=%s] .item-latest-version' % app.id
                ).text(),
            'Pending Version: 1.24')

    def test_action_links(self):
        self.create_switch('app-stats')
        app = self.get_app()
        app.update(public_stats=True, is_packaged=False)
        self.make_mine()
        doc = pq(self.client.get(self.url).content)
        expected = [
            ('Edit Listing', app.get_dev_url()),
            ('Manage Authors', app.get_dev_url('owner')),
            ('Compatibility & Payments', app.get_dev_url('payments')),
            ('Manage Status', app.get_dev_url('versions')),
            ('View Listing', app.get_url_path()),
        ]
        amo.tests.check_links(expected, doc('a.action-link'))
        amo.tests.check_links([('View Statistics', app.get_stats_url())],
                              doc('a.stats-link'), verify=False)

    def test_action_links_packaged(self):
        self.create_switch('app-stats')
        app = self.get_app()
        app.update(public_stats=True, is_packaged=True)
        self.make_mine()
        doc = pq(self.client.get(self.url).content)
        expected = [
            ('Edit Listing', app.get_dev_url()),
            ('Add New Version', app.get_dev_url('versions')),
            ('Manage Authors', app.get_dev_url('owner')),
            ('Compatibility & Payments', app.get_dev_url('payments')),
            ('Manage Status & Versions', app.get_dev_url('versions')),
            ('View Listing', app.get_url_path()),
        ]
        amo.tests.check_links(expected, doc('a.action-link'))
        amo.tests.check_links([('View Statistics', app.get_stats_url())],
                              doc('a.stats-link'), verify=False)

    def test_disabled_payments_action_links(self):
        self.create_switch('app-stats')
        self.create_switch('disabled-payments')
        app = self.get_app()
        app.update(public_stats=True)
        self.make_mine()
        doc = pq(self.client.get(self.url).content)
        expected = [
            ('Edit Listing', app.get_dev_url()),
            ('Manage Authors', app.get_dev_url('owner')),
            ('Manage Status', app.get_dev_url('versions')),
            ('View Listing', app.get_url_path()),
            ('View Statistics', app.get_stats_url()),
        ]
        amo.tests.check_links(expected, doc('a.action-link'), verify=False)

    def test_action_links_with_payments(self):
        self.create_switch('in-app-payments')
        app = self.get_app()
        for status in [amo.ADDON_PREMIUM_INAPP, amo.ADDON_FREE_INAPP]:
            app.update(premium_type=status)
            self.make_mine()
            doc = pq(self.client.get(self.url).content)
            expected = [
                ('Manage Status', app.get_dev_url('versions')),
                ('Manage In-App Payments', app.get_dev_url('in_app_config')),
            ]
            eq_(doc('.status-link').length, 0)
            amo.tests.check_links(expected, doc('.more-actions-popup a'))

    def test_disabled_payments_action_links_with_payments(self):
        self.create_switch('in-app-payments')
        self.create_switch('disabled-payments')
        app = self.get_app()
        for status in [amo.ADDON_PREMIUM_INAPP, amo.ADDON_FREE_INAPP]:
            app.update(premium_type=status)
            self.make_mine()
            doc = pq(self.client.get(self.url).content)
            status_link = doc('.status-link')
            eq_(status_link.length, 1)
            eq_(status_link.attr('href'), app.get_dev_url('versions'))
            eq_(doc('.more-actions-popup').length, 0)


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


class MarketplaceMixin(object):

    def setUp(self):
        self.create_switch('allow-b2g-paid-submission')

        self.addon = Addon.objects.get(id=337141)
        self.addon.update(status=amo.STATUS_NOMINATED,
                          highest_status=amo.STATUS_NOMINATED)

        self.url = self.addon.get_dev_url('payments')
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')

    def setup_premium(self):
        self.price = Price.objects.create(price='0.99')
        self.price_two = Price.objects.create(price='1.99')
        self.other_addon = Addon.objects.create(type=amo.ADDON_WEBAPP,
                                                premium_type=amo.ADDON_FREE)
        self.other_addon.update(status=amo.STATUS_PUBLIC)
        AddonUser.objects.create(addon=self.other_addon,
                                 user=self.addon.authors.all()[0])
        AddonPremium.objects.create(addon=self.addon, price_id=self.price.pk)
        self.addon.update(premium_type=amo.ADDON_PREMIUM)


@mock.patch('mkt.developers.forms.PremiumForm.clean',
            new=lambda x: x.cleaned_data)
class TestMarketplace(MarketplaceMixin, amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube', 'market/prices']

    def get_data(self, **kw):
        data = {
            'price': self.price.pk,
            'upsell_of': self.other_addon.pk,
        }
        data.update(kw)
        return data

    def test_initial_free(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        assert 'Change to Paid' in res.content

    def test_initial_paid(self):
        self.setup_premium()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(res.context['form'].initial['price'], self.price)
        assert 'Change to Free' in res.content

    def test_set(self):
        self.setup_premium()
        res = self.client.post(
            self.url, data=self.get_data(price=self.price_two.pk))
        eq_(res.status_code, 302)
        self.addon = Addon.objects.get(pk=self.addon.pk)
        eq_(self.addon.addonpremium.price, self.price_two)

    def test_set_currency(self):
        self.setup_premium()
        res = self.client.post(
            self.url, data=self.get_data(currencies=['EUR', 'BRL']))
        eq_(res.status_code, 302)
        self.addon = Addon.objects.get(pk=self.addon.pk)
        eq_(self.addon.premium.currencies, ['EUR', 'BRL'])

    def test_set_currency_fail(self):
        self.setup_premium()
        res = self.client.post(
            self.url, data=self.get_data(currencies=['EUR', 'LOL']),
            follow=True)
        eq_(res.status_code, 200)
        self.assertFormError(res, 'form', 'currencies',
                             [u'Select a valid choice. '
                               'LOL is not one of the available choices.'])

    def test_set_upsell(self):
        self.setup_premium()
        res = self.client.post(self.url, data=self.get_data())
        eq_(res.status_code, 302)
        eq_(len(self.addon._upsell_to.all()), 1)

    def test_remove_upsell(self):
        self.setup_premium()
        upsell = AddonUpsell.objects.create(
            free=self.other_addon, premium=self.addon)
        eq_(self.addon._upsell_to.all()[0], upsell)
        self.client.post(self.url, data=self.get_data(upsell_of=''))
        eq_(len(self.addon._upsell_to.all()), 0)

    def test_replace_upsell(self):
        self.setup_premium()
        # Make this add-on an upsell of some free add-on.
        upsell = AddonUpsell.objects.create(free=self.other_addon,
                                            premium=self.addon)
        # And this will become our new upsell, replacing the one above.
        new = Addon.objects.create(type=amo.ADDON_WEBAPP,
                                   premium_type=amo.ADDON_FREE,
                                   status=amo.STATUS_PUBLIC)
        AddonUser.objects.create(addon=new, user=self.addon.authors.all()[0])

        eq_(self.addon._upsell_to.all()[0], upsell)
        self.client.post(self.url, self.get_data(upsell_of=new.id))
        upsell = self.addon._upsell_to.all()
        eq_(len(upsell), 1)
        eq_(upsell[0].free, new)


class TestPublicise(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.webapp.update(status=amo.STATUS_PUBLIC_WAITING)
        self.file = self.webapp.versions.latest().all_files[0]
        self.file.update(status=amo.STATUS_PUBLIC_WAITING)
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
        eq_(self.get_webapp().versions.latest().all_files[0].status,
            amo.STATUS_PUBLIC)

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
        self.assertRedirects(r, self.webapp.get_dev_url('edit'), 302)

    def test_step_redirects(self):
        AppSubmissionChecklist.objects.create(addon=self.webapp,
                                              terms=True, manifest=True)
        r = self.client.get(self.url, follow=True)
        self.assert3xx(r, reverse('submit.app.details',
                                  args=[self.webapp.app_slug]))

    def test_no_resume_when_done(self):
        AppSubmissionChecklist.objects.create(addon=self.webapp,
                                              terms=True, manifest=True,
                                              details=True)
        r = self.client.get(self.webapp.get_dev_url('edit'), follow=True)
        eq_(r.status_code, 200)

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
        path = u'apps/files/fixtures/files/jetpack.xpi'
        data = storage.open(os.path.join(settings.ROOT, path))
        replaced = path.replace('e', u'é')
        r = self.client.post(self.url, {'upload':
                                        SimpleUploadedFile(replaced,
                                                           data.read())})
        # If this is broke, we'll get a traceback.
        eq_(r.status_code, 302)

    @mock.patch('mkt.constants.MAX_PACKAGED_APP_SIZE', 1024)
    @mock.patch('mkt.developers.tasks.validator')
    def test_fileupload_too_big(self, validator):
        with tempfile.NamedTemporaryFile(delete=False) as tf:
            name = tf.name
            tf.write('x' * (MAX_PACKAGED_APP_SIZE + 1))

        with open(name) as tf:
            r = self.client.post(self.url, {'upload': tf})

        os.unlink(name)

        assert not validator.called, 'Validator erroneously invoked'

        # Test that we get back a validation failure for the upload.
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('mkt.developers.upload_detail',
                                    args=[upload.uuid, 'json']))

        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert 'validation' in data, data
        assert 'success' in data['validation'], data
        assert not data['validation']['success'], data['validation']

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
    fixtures = ['base/apps', 'base/appversion', 'base/platforms', 'base/users']

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
                    args=['hosted', upload.uuid]))
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

    @mock.patch.object(settings, 'DEV_AGREEMENT_LAST_UPDATED',
                       amo.tests.days_ago(-5).date())
    def test_update(self):
        past = self.days_ago(10)
        self.user.update(read_dev_agreement=past)
        res = self.client.post(self.url, {'read_dev_agreement': 'yeah'})
        eq_(res.status_code, 200)
        assert self.get_user().read_dev_agreement != past

    @mock.patch.object(settings, 'DEV_AGREEMENT_LAST_UPDATED',
                       amo.tests.days_ago(-5).date())
    def test_past(self):
        past = self.days_ago(10)
        self.user.update(read_dev_agreement=past)
        res = self.client.get(self.url)
        doc = pq(res.content)
        eq_(doc('#site-notice').length, 1)
        eq_(doc('#dev-agreement').length, 1)
        eq_(doc('#agreement-form').length, 1)

    def test_not_past(self):
        res = self.client.get(self.url)
        doc = pq(res.content)
        eq_(doc('#site-notice').length, 0)
        eq_(doc('#dev-agreement').length, 1)
        eq_(doc('#agreement-form').length, 0)
