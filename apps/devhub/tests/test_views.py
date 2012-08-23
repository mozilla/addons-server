# -*- coding: utf-8 -*-
import json
import os
import socket
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core import mail
from django.utils.http import urlencode
from django.core.files.storage import default_storage as storage

import jingo
import mock
import waffle
from jingo.helpers import datetime as datetime_filter
from nose.plugins.attrib import attr
from nose.tools import assert_not_equal, assert_raises, eq_
from PIL import Image
from pyquery import PyQuery as pq
from tower import strip_whitespace
# Unused, but needed so that we can patch jingo.
from waffle import helpers

import amo
import amo.tests
import files
import paypal
from addons import cron
from addons.models import (Addon, AddonCategory, AddonUpsell, AddonUser,
                           Category, Charity)
from amo.helpers import (absolutify, babel_datetime, url as url_reverse,
                         timesince)
from amo.tests import (addon_factory, assert_no_validation_errors,
                       close_to_now, formset, initial)
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
from applications.models import Application, AppVersion
from devhub.forms import ContribForm
from devhub.models import ActivityLog, BlogPost, SubmitStep
from devhub import tasks
from files.models import File, FileUpload, Platform
from files.tests.test_models import UploadTest as BaseUploadTest
from market.models import AddonPremium, Price, Refund
from reviews.models import Review
from stats.models import Contribution
from translations.models import Translation
from users.models import UserProfile
from versions.models import ApplicationsVersions, License, Version


class MetaTests(amo.tests.TestCase):

    def test_assert_close_to_now(dt):
        assert close_to_now(datetime.now() - timedelta(seconds=30))
        assert not close_to_now(datetime.now() + timedelta(days=30))
        assert not close_to_now(datetime.now() + timedelta(minutes=3))
        assert not close_to_now(datetime.now() + timedelta(seconds=30))


class HubTest(amo.tests.TestCase):
    fixtures = ['browse/nameless-addon', 'base/users']

    def setUp(self):
        self.url = reverse('devhub.index')
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


class TestHome(HubTest):

    def test_addons(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        self.assertTemplateUsed(r, 'devhub/index.html')


class TestNav(HubTest):

    def test_navbar(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#site-nav').length, 1)

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert_not_equal(doc('#navbar ul li.top a').eq(0).text(),
            'My Add-ons',
            'My Add-ons menu should not be visible if user has no add-ons.')

    def test_my_addons(self):
        """Check that the correct items are listed for the My Add-ons menu."""
        # Assign this add-on to the current user profile.
        addon = Addon.objects.get(id=57132)
        addon.name = 'Test'
        addon.save()
        AddonUser.objects.create(user=self.user_profile, addon=addon)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # Check the anchor for the 'My Add-ons' menu item.
        eq_(doc('#site-nav ul li.top a').eq(0).text(), 'My Add-ons')

        # Check the anchor for the single add-on.
        eq_(doc('#site-nav ul li.top li a').eq(0).attr('href'),
            addon.get_dev_url())

        # Create 6 add-ons.
        self.clone_addon(6)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # There should be 8 items in this menu.
        eq_(doc('#site-nav ul li.top').eq(0).find('ul li').length, 8)

        # This should be the 8th anchor, after the 7 addons.
        eq_(doc('#site-nav ul li.top').eq(0).find('li a').eq(7).text(),
            'Submit a New Add-on')

        self.clone_addon(1)

        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#site-nav ul li.top').eq(0).find('li a').eq(7).text(),
            'more add-ons...')

    def test_only_one_header(self):
        # For bug 682359.
        # Remove this test when we switch to Impala in the devhub!
        doc = pq(self.client.get(reverse('devhub.addons')).content)
        # Make sure we're on a non-impala page.
        eq_(doc('.is-impala').length, 0,
            'This test should be run on a non-impala page.')
        eq_(doc('#header').length, 0, 'Uh oh, there are two headers!')


class TestDashboard(HubTest):

    def setUp(self):
        super(TestDashboard, self).setUp()
        self.url = reverse('devhub.addons')
        self.apps_url = reverse('devhub.apps')
        eq_(self.client.get(self.url).status_code, 200)

    def test_addons_layout(self):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('title').text(),
            'Manage My Add-ons :: Developer Hub :: Add-ons for Firefox')
        eq_(doc('#social-footer').length, 1)
        eq_(doc('#copyright').length, 1)
        eq_(doc('#footer-links .mobile-link').length, 0)

    def get_action_links(self, addon_id):
        r = self.client.get(self.url)
        doc = pq(r.content)
        links = [a.text.strip() for a in
                 doc('.item[data-addonid=%s] .item-actions li > a' % addon_id)]
        return links

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('.item item').length, 0)

    def test_addon_pagination(self):
        """Check that the correct info. is displayed for each add-on:
        namely, that add-ons are paginated at 10 items per page, and that
        when there is more than one page, the 'Sort by' header and pagination
        footer appear.

        """
        # Create 10 add-ons.
        self.clone_addon(10)
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(len(doc('.item .item-info')), 10)
        eq_(doc('nav.paginator').length, 0)

        # Create 5 add-ons.
        self.clone_addon(5)
        r = self.client.get(self.url, dict(page=2))
        doc = pq(r.content)
        eq_(len(doc('.item .item-info')), 5)
        eq_(doc('nav.paginator').length, 1)

    def test_show_hide_statistics(self):
        a_pk = self.clone_addon(1)[0]

        # when Active and Public show statistics
        Addon.objects.get(pk=a_pk).update(disabled_by_user=False,
                                          status=amo.STATUS_PUBLIC)
        links = self.get_action_links(a_pk)
        assert 'Statistics' in links, ('Unexpected: %r' % links)

        # when Active and Incomplete hide statistics
        Addon.objects.get(pk=a_pk).update(disabled_by_user=False,
                                          status=amo.STATUS_NULL)
        links = self.get_action_links(a_pk)
        assert 'Statistics' not in links, ('Unexpected: %r' % links)

    def test_public_addon(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        addon = Addon.objects.get(id=self.clone_addon(1)[0])
        eq_(addon.status, amo.STATUS_PUBLIC)
        doc = pq(self.client.get(self.url).content)
        item = doc('.item[data-addonid=%s]' % addon.id)
        eq_(item.find('h3 a').attr('href'), addon.get_dev_url())
        assert item.find('p.downloads'), 'Expected weekly downloads'
        assert item.find('p.users'), 'Expected ADU'
        assert item.find('.price'), 'Expected price'
        assert item.find('.item-details'), 'Expected item details'
        assert not item.find('p.incomplete'), (
            'Unexpected message about incomplete add-on')

    def test_incomplete_addon(self):
        waffle.models.Switch.objects.create(name='marketplace', active=True)
        addon = Addon.objects.get(id=self.clone_addon(1)[0])
        addon.update(status=amo.STATUS_NULL)
        doc = pq(self.client.get(self.url).content)
        item = doc('.item[data-addonid=%s]' % addon.id)
        assert not item.find('h3 a'), 'Unexpected link to add-on'
        assert not item.find('.item-details'), 'Unexpected item details'
        assert not item.find('.price'), 'Expected price'
        assert item.find('p.incomplete'), (
            'Expected message about incompleted add-on')

    def test_dev_news(self):
        self.clone_addon(1)  # We need one to see this module
        for i in xrange(7):
            bp = BlogPost(title='hi %s' % i,
                          date_posted=datetime.now() - timedelta(days=i))
            bp.save()
        r = self.client.get(self.url)
        doc = pq(r.content)

        eq_(doc('.blog-posts').length, 1)
        eq_(doc('.blog-posts li').length, 5)
        eq_(doc('.blog-posts li a').eq(0).text(), "hi 0")
        eq_(doc('.blog-posts li a').eq(4).text(), "hi 4")

    def test_sort_created_filter(self):
        a_pk = self.clone_addon(1)[0]
        addon = Addon.objects.get(pk=a_pk)
        response = self.client.get(self.url + '?sort=created')
        doc = pq(response.content)
        eq_(doc('.item-details').length, 1)
        d = doc('.item-details .date-created')
        eq_(d.length, 1)
        eq_(d.remove('strong').text(),
            strip_whitespace(datetime_filter(addon.created)))

    def test_sort_updated_filter(self):
        a_pk = self.clone_addon(1)[0]
        addon = Addon.objects.get(pk=a_pk)
        response = self.client.get(self.url)
        doc = pq(response.content)
        eq_(doc('.item-details').length, 1)
        d = doc('.item-details .date-updated')
        eq_(d.length, 1)
        eq_(d.remove('strong').text(),
            strip_whitespace(datetime_filter(addon.last_updated)))


class TestUpdateCompatibility(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_4594_a9',
                'base/addon_3615']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.url = reverse('devhub.addons')

        # TODO(andym): use Mock appropriately here.
        self._versions = amo.FIREFOX.latest_version, amo.MOBILE.latest_version
        amo.FIREFOX.latest_version = amo.MOBILE.latest_version = '3.6.15'

    def tearDown(self):
        amo.FIREFOX.latest_version, amo.MOBILE.latest_version = self._versions

    def test_no_compat(self):
        self.client.logout()
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert not doc('.item[data-addonid=4594] li.compat')
        a = Addon.objects.get(pk=4594)
        r = self.client.get(reverse('devhub.ajax.compat.update',
                                    args=[a.slug, a.current_version.id]))
        eq_(r.status_code, 404)
        r = self.client.get(reverse('devhub.ajax.compat.status',
                                    args=[a.slug]))
        eq_(r.status_code, 404)

    def test_compat(self):
        a = Addon.objects.get(pk=3615)

        r = self.client.get(self.url)
        doc = pq(r.content)
        cu = doc('.item[data-addonid=3615] .tooltip.compat-update')
        assert cu

        update_url = reverse('devhub.ajax.compat.update',
                             args=[a.slug, a.current_version.id])
        eq_(cu.attr('data-updateurl'), update_url)

        status_url = reverse('devhub.ajax.compat.status', args=[a.slug])
        eq_(doc('.item[data-addonid=3615] li.compat').attr('data-src'),
            status_url)

        assert doc('.item[data-addonid=3615] .compat-update-modal')

    def test_incompat_firefox(self):
        versions = ApplicationsVersions.objects.all()[0]
        versions.max = AppVersion.objects.get(version='2.0')
        versions.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('.item[data-addonid=3615] .tooltip.compat-error')

    def test_incompat_mobile(self):
        app = Application.objects.get(id=amo.MOBILE.id)
        appver = AppVersion.objects.get(version='2.0')
        appver.update(application=app)
        av = ApplicationsVersions.objects.all()[0]
        av.application = app
        av.max = appver
        av.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('.item[data-addonid=3615] .tooltip.compat-error')


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

        url = reverse('devhub.versions.stats', args=[addon.slug])
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

    def test_logging(self):
        count = ActivityLog.objects.all().count()
        self.post(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                  annoying=amo.CONTRIB_AFTER)
        eq_(ActivityLog.objects.all().count(), count + 1)

    def test_success_dev(self):
        self.post(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                  annoying=amo.CONTRIB_AFTER)
        self.check(paypal_id='greed@dev', suggested_amount=2,
                   annoying=amo.CONTRIB_AFTER)

    def test_success_foundation(self):
        self.post(recipient='moz', suggested_amount=2,
                  annoying=amo.CONTRIB_ROADBLOCK)
        self.check(paypal_id='', suggested_amount=2,
                   charity=self.foundation, annoying=amo.CONTRIB_ROADBLOCK)

    def test_success_charity(self):
        d = dict(recipient='org', suggested_amount=11.5,
                 annoying=amo.CONTRIB_PASSIVE)
        d.update({'charity-name': 'fligtar fund',
                  'charity-url': 'http://feed.me',
                  'charity-paypal': 'greed@org'})
        self.post(d)
        self.check(paypal_id='', suggested_amount=Decimal('11.50'),
                   charity=Charity.objects.get(name='fligtar fund'))

    def test_dev_paypal_id_length(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(int(doc('#id_paypal_id').attr('size')), 50)

    def test_dev_paypal_reqd(self):
        d = dict(recipient='dev', suggested_amount=2,
                 annoying=amo.CONTRIB_PASSIVE)
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'contrib_form', 'paypal_id',
                             'PayPal ID required to accept contributions.')

    def test_bad_paypal_id_dev(self):
        self.paypal_mock.return_value = False, 'error'
        d = dict(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                 annoying=amo.CONTRIB_AFTER)
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'contrib_form', 'paypal_id', 'error')

    def test_bad_paypal_id_charity(self):
        self.paypal_mock.return_value = False, 'error'
        d = dict(recipient='org', suggested_amount=11.5,
                 annoying=amo.CONTRIB_PASSIVE)
        d.update({'charity-name': 'fligtar fund',
                  'charity-url': 'http://feed.me',
                  'charity-paypal': 'greed@org'})
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'charity_form', 'paypal', 'error')

    def test_paypal_timeout(self):
        self.paypal_mock.side_effect = socket.timeout()
        d = dict(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                 annoying=amo.CONTRIB_AFTER)
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'contrib_form', 'paypal_id',
                             'Could not validate PayPal id.')

    def test_max_suggested_amount(self):
        too_much = settings.MAX_CONTRIBUTION + 1
        msg = ('Please enter a suggested amount less than $%d.' %
               settings.MAX_CONTRIBUTION)
        r = self.client.post(self.url, {'suggested_amount': too_much})
        self.assertFormError(r, 'contrib_form', 'suggested_amount', msg)

    def test_neg_suggested_amount(self):
        msg = 'Please enter a suggested amount greater than 0.'
        r = self.client.post(self.url, {'suggested_amount': -1})
        self.assertFormError(r, 'contrib_form', 'suggested_amount', msg)

    def test_charity_details_reqd(self):
        d = dict(recipient='org', suggested_amount=11.5,
                 annoying=amo.CONTRIB_PASSIVE)
        r = self.client.post(self.url, d)
        self.assertFormError(r, 'charity_form', 'name',
                             'This field is required.')
        eq_(self.get_addon().suggested_amount, None)

    def test_switch_charity_to_dev(self):
        self.test_success_charity()
        self.test_success_dev()
        eq_(self.get_addon().charity, None)
        eq_(self.get_addon().charity_id, None)

    def test_switch_charity_to_foundation(self):
        self.test_success_charity()
        self.test_success_foundation()
        # This will break if we start cleaning up licenses.
        old_charity = Charity.objects.get(name='fligtar fund')
        assert old_charity.id != self.foundation

    def test_switch_foundation_to_charity(self):
        self.test_success_foundation()
        self.test_success_charity()
        moz = Charity.objects.get(id=self.foundation.id)
        eq_(moz.name, 'moz')
        eq_(moz.url, '$$.moz')
        eq_(moz.paypal, 'moz.pal')

    def test_contrib_form_initial(self):
        eq_(ContribForm.initial(self.addon)['recipient'], 'dev')
        self.addon.charity = self.foundation
        eq_(ContribForm.initial(self.addon)['recipient'], 'moz')
        self.addon.charity_id = amo.FOUNDATION_ORG + 1
        eq_(ContribForm.initial(self.addon)['recipient'], 'org')

        eq_(ContribForm.initial(self.addon)['annoying'], amo.CONTRIB_PASSIVE)
        self.addon.annoying = amo.CONTRIB_AFTER
        eq_(ContribForm.initial(self.addon)['annoying'], amo.CONTRIB_AFTER)

    def test_enable_thankyou(self):
        d = dict(enable_thankyou='on', thankyou_note='woo',
                 annoying=1, recipient='moz')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        addon = self.get_addon()
        eq_(addon.enable_thankyou, True)
        eq_(unicode(addon.thankyou_note), 'woo')

    def test_enable_thankyou_unchecked_with_text(self):
        d = dict(enable_thankyou='', thankyou_note='woo',
                 annoying=1, recipient='moz')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        addon = self.get_addon()
        eq_(addon.enable_thankyou, False)
        eq_(addon.thankyou_note, None)

    def test_contribution_link(self):
        self.test_success_foundation()
        r = self.client.get(self.url)
        doc = pq(r.content)

        span = doc('#status-bar').find('span')
        eq_(span.length, 1)
        assert span.text().startswith('Your contribution page: ')

        a = span.find('a')
        eq_(a.length, 1)
        eq_(a.attr('href'), reverse('addons.about',
                                    args=[self.get_addon().slug]))
        eq_(a.text(), url_reverse('addons.about', self.get_addon().slug,
                                  host=settings.SITE_URL))

    def test_enable_thankyou_no_text(self):
        d = dict(enable_thankyou='on', thankyou_note='',
                 annoying=1, recipient='moz')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        addon = self.get_addon()
        eq_(addon.enable_thankyou, False)
        eq_(addon.thankyou_note, None)

    def test_no_future(self):
        self.get_addon().update(the_future=None)
        res = self.client.get(self.url)
        err = pq(res.content)('p.error').text()
        eq_('completed developer profile' in err, True)

    def test_with_upsell_no_contributions(self):
        AddonUpsell.objects.create(free=self.addon, premium=self.addon)
        res = self.client.get(self.url)
        error = pq(res.content)('p.error').text()
        eq_('premium add-on enrolled' in error, True)
        eq_(' %s' % self.addon.name in error, True)

    @mock.patch.dict(jingo.env.globals['waffle'], {'switch': lambda x: True})
    def test_addon_public(self):
        self.get_addon().update(status=amo.STATUS_PUBLIC)
        res = self.client.get(self.url)
        doc = pq(res.content)
        eq_(doc('#do-setup').text(), 'Set up Contributions')
        eq_('You cannot enroll in the Marketplace' in doc('p.error').text(),
            True)

    @mock.patch.dict(jingo.env.globals['waffle'], {'switch': lambda x: True})
    def test_addon_not_reviewed(self):
        self.get_addon().update(status=amo.STATUS_NULL,
                                highest_status=amo.STATUS_NULL)
        res = self.client.get(self.url)
        doc = pq(res.content)
        eq_(doc('#do-marketplace').text(), 'Enroll in Marketplace')
        eq_('fully reviewed add-ons' in doc('p.error').text(), True)

    @mock.patch('addons.models.Addon.upsell')
    def test_upsell(self, upsell):
        upsell.return_value = self.get_addon()
        d = dict(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                 annoying=amo.CONTRIB_AFTER)
        res = self.client.post(self.url, d)
        eq_('premium add-on' in res.content, True)

    @mock.patch.dict(jingo.env.globals['waffle'], {'switch': lambda x: True})
    def test_voluntary_contributions_addons(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('.intro').length, 2)
        eq_(doc('.intro.full-intro').length, 0)


class TestDisablePayments(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        self.addon.update(wants_contributions=True, paypal_id='woohoo')
        self.pay_url = self.addon.get_dev_url('payments')
        self.disable_url = self.addon.get_dev_url('payments.disable')
        assert self.client.login(username='del@icio.us', password='password')

    def test_statusbar_visible(self):
        r = self.client.get(self.pay_url)
        self.assertContains(r, '<div id="status-bar">')

        self.addon.update(wants_contributions=False)
        r = self.client.get(self.pay_url)
        self.assertNotContains(r, '<div id="status-bar">')

    def test_disable(self):
        r = self.client.post(self.disable_url)
        eq_(r.status_code, 302)
        assert(r['Location'].endswith(self.pay_url))
        eq_(Addon.uncached.get(id=3615).wants_contributions, False)


class TestPaymentsProfile(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = a = self.get_addon()
        self.url = self.addon.get_dev_url('payments')
        # Make sure all the payment/profile data is clear.
        assert not (a.wants_contributions or a.paypal_id or a.the_reason
                    or a.the_future or a.takes_contributions)
        assert self.client.login(username='del@icio.us', password='password')
        self.paypal_mock = mock.Mock()
        self.paypal_mock.return_value = (True, None)
        paypal.check_paypal_id = self.paypal_mock

    def get_addon(self):
        return Addon.objects.get(id=3615)

    def test_intro_box(self):
        # We don't have payments/profile set up, so we see the intro.
        doc = pq(self.client.get(self.url).content)
        assert doc('.intro')
        assert doc('#setup.hidden')

    def test_status_bar(self):
        # We don't have payments/profile set up, so no status bar.
        doc = pq(self.client.get(self.url).content)
        assert not doc('#status-bar')

    def test_profile_form_exists(self):
        doc = pq(self.client.get(self.url).content)
        assert doc('#trans-the_reason')
        assert doc('#trans-the_future')

    def test_profile_form_success(self):
        d = dict(recipient='dev', suggested_amount=2, paypal_id='xx@yy',
                 annoying=amo.CONTRIB_ROADBLOCK, the_reason='xxx',
                 the_future='yyy')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)

        # The profile form is gone, we're accepting contributions.
        doc = pq(self.client.get(self.url).content)
        assert not doc('.intro')
        assert not doc('#setup.hidden')
        assert doc('#status-bar')
        assert not doc('#trans-the_reason')
        assert not doc('#trans-the_future')

        addon = self.get_addon()
        eq_(unicode(addon.the_reason), 'xxx')
        eq_(unicode(addon.the_future), 'yyy')
        eq_(addon.wants_contributions, True)

    def test_profile_required(self):
        def check_page(request):
            doc = pq(request.content)
            assert not doc('.intro')
            assert not doc('#setup.hidden')
            assert not doc('#status-bar')
            assert doc('#trans-the_reason')
            assert doc('#trans-the_future')

        d = dict(recipient='dev', suggested_amount=2, paypal_id='xx@yy',
                 annoying=amo.CONTRIB_ROADBLOCK)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'profile_form', 'the_reason',
                             'This field is required.')
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')
        check_page(r)
        eq_(self.get_addon().wants_contributions, False)

        d = dict(recipient='dev', suggested_amount=2, paypal_id='xx@yy',
                 annoying=amo.CONTRIB_ROADBLOCK, the_reason='xxx')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')
        check_page(r)
        eq_(self.get_addon().wants_contributions, False)

    def test_checker_no_email(self):
        url = reverse('devhub.check_paypal')
        r = self.client.post(url)
        eq_(r.status_code, 404)

    @mock.patch('paypal.check_paypal_id')
    @mock.patch('paypal.get_paykey')
    def test_checker_valid_email(self, gp, cpi):
        cpi.return_value = (True, "")
        gp.return_value = "123abc"

        url = reverse('devhub.check_paypal')
        r = self.client.post(url, {'email': 'test@test.com'})
        eq_(r.status_code, 200)
        result = json.loads(r.content)
        eq_(result['valid'], True)

    @mock.patch('paypal.check_paypal_id')
    @mock.patch('paypal.get_paykey')
    def test_checker_invalid_email(self, gp, cpi):
        cpi.return_value = (False, "Oh no you didn't")
        gp.return_value = "123abc"

        url = reverse('devhub.check_paypal')
        r = self.client.post(url, {'email': 'test.com'})
        eq_(r.status_code, 200)
        result = json.loads(r.content)

        eq_(result[u'valid'], False)
        assert len(result[u'message']) > 0, "No error on invalid email"

    @mock.patch('paypal.check_paypal_id')
    @mock.patch('paypal.get_paykey')
    def test_checker_no_paykey(self, gp, cpi):
        cpi.return_value = (True, "")
        gp.side_effect = paypal.PaypalError()

        url = reverse('devhub.check_paypal')
        r = self.client.post(url, {'email': 'test@test.com'})
        eq_(r.status_code, 200)
        result = json.loads(r.content)

        eq_(result[u'valid'], False)
        assert len(result[u'message']) > 0, "No error on missing paykey"

    @mock.patch('paypal.get_paykey')
    def test_checker_no_pre_approval(self, get_paykey):
        self.client.post(reverse('devhub.check_paypal'),
                         {'email': 'test@test.com'})
        assert 'preapprovalKey' not in get_paykey.call_args[0][0]


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
        AddonUser.objects.create(addon=self.other_addon,
                                 user=self.addon.authors.all()[0])
        AddonPremium.objects.create(addon=self.addon, price_id=self.price.pk)
        self.addon.update(premium_type=amo.ADDON_PREMIUM,
                          paypal_id='a@a.com')


class TestRefundToken(MarketplaceMixin, amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def test_no_token(self):
        self.setup_premium()
        res = self.client.post(self.url, {"paypal_id": "a@a.com",
                                          "support_email": "dev@example.com"})
        assert 'refund token' in pq(res.content)('.notification-box')[0].text

    @mock.patch('paypal.check_permission')
    def test_with_token(self, cp):
        cp.return_value = True
        self.setup_premium()
        self.addon.addonpremium.update(paypal_permissions_token='foo')
        res = self.client.post(self.url, {"paypal_id": "a@a.com",
                                          "support_email": "dev@example.com"})
        assert not pq(res.content)('.notification-box')


# Mock out verfiying the paypal id has refund permissions with paypal and
# that the account exists on paypal.
#
@mock.patch('devhub.forms.PremiumForm.clean_paypal_id',
            new=lambda x: x.cleaned_data['paypal_id'])
@mock.patch('devhub.forms.PremiumForm.clean', new=lambda x: x.cleaned_data)
class TestMarketplace(MarketplaceMixin, amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    @mock.patch('addons.models.Addon.can_become_premium')
    def test_ask_page(self, can_become_premium):
        can_become_premium.return_value = True
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(len(doc('div.intro')), 2)

    @mock.patch('addons.models.Addon.can_become_premium')
    def test_no_warning(self, can_become_premium):
        can_become_premium.return_value = True
        doc = pq(self.client.get(self.url).content)
        eq_(len(doc('div.notification-box')), 0)

    @mock.patch('addons.models.Addon.can_become_premium')
    def test_warning(self, can_become_premium):
        can_become_premium.return_value = True
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        doc = pq(self.client.get(self.url).content)
        eq_(len(doc('div.notification-box')), 1)

    @mock.patch('addons.models.Addon.can_become_premium')
    def test_cant_become_premium(self, can_become_premium):
        can_become_premium.return_value = False
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        eq_(len(doc('.error')), 2)

    @mock.patch('addons.models.Addon.upsell')
    def test_addon_upsell(self, upsell):
        upsell.return_value = True
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert 'You cannot enroll in the Marketplace' in doc('p.error').text()

    def get_data(self):
        return {
            'paypal_id': 'a@a.com',
            'price': self.price.pk,
            'free': self.other_addon.pk,
            'support_email': 'b@b.com',
            'do_upsell': 1,
            'text': 'some upsell',
        }

    def test_template_premium(self):
        self.setup_premium()
        res = self.client.get(self.url)
        self.assertTemplateUsed(res, 'devhub/payments/premium.html')

    def test_template_free(self):
        res = self.client.get(self.url)
        self.assertTemplateUsed(res, 'devhub/payments/payments.html')

    def test_initial(self):
        self.setup_premium()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(res.context['form'].initial['price'], self.price)
        eq_(res.context['form'].initial['paypal_id'], 'a@a.com')

    def test_set(self):
        self.setup_premium()
        res = self.client.post(self.url, data={
            'paypal_id': 'b@b.com',
            'support_email': 'c@c.com',
            'price': self.price_two.pk,
        })
        eq_(res.status_code, 302)
        self.addon = Addon.objects.get(pk=self.addon.pk)
        eq_(self.addon.paypal_id, 'b@b.com')
        eq_(self.addon.addonpremium.price, self.price_two)

    def test_set_upsell(self):
        self.setup_premium()
        res = self.client.post(self.url, data=self.get_data())
        eq_(res.status_code, 302)
        eq_(len(self.addon._upsell_to.all()), 1)

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
    def test_permissions_token(self):
        self.setup_premium()
        eq_(self.addon.premium.paypal_permissions_token, '')
        url = self.addon.get_dev_url('acquire_refund_permission')
        data = {'request_token': 'foo', 'verification_code': 'bar'}
        self.client.get('%s?%s' % (url, urlencode(data)))
        self.addon = Addon.objects.get(pk=self.addon.pk)
        eq_(self.addon.premium.paypal_permissions_token, 'FOO')

    @mock.patch('paypal.get_permissions_token', lambda x, y: x.upper())
    def test_permissions_token_redirect(self):
        self.setup_premium()
        eq_(self.addon.premium.paypal_permissions_token, '')
        url = reverse('devhub.addons.acquire_refund_permission',
                      args=[self.addon.slug])
        data = {'request_token': 'foo', 'verification_code': 'bar'}
        res = self.client.get(url, data=data)
        assert res['Location'].endswith(reverse('devhub.addons.payments',
                                                args=[self.addon.slug]))

        data['dest'] = 'wizard'
        res = self.client.get(url, data=data)
        assert res['Location'].endswith(reverse('devhub.addons.market.1',
                                                args=[self.addon.slug]))

    @mock.patch('paypal.get_permissions_token', lambda x, y: x.upper())
    def test_permissions_token_no_premium(self):
        self.setup_premium()
        # They could hit this URL before anything else, we need to cope
        # with AddonPremium not being there.
        self.addon.premium.delete()
        self.addon.update(premium_type=amo.ADDON_FREE)
        url = self.addon.get_dev_url('acquire_refund_permission')
        data = {'request_token': 'foo', 'verification_code': 'bar'}
        self.client.get('%s?%s' % (url, urlencode(data)))
        self.addon = Addon.objects.get(pk=self.addon.pk)
        eq_(self.addon.addonpremium.paypal_permissions_token, 'FOO')

    def test_wizard_step_1(self):
        url = self.addon.get_dev_url('market.1')
        data = {'paypal_id': 'some@paypal.com', 'support_email': 'a@a.com'}
        eq_(self.client.post(url, data).status_code, 302)
        addon = Addon.objects.get(pk=self.addon.pk)
        eq_(addon.paypal_id, data['paypal_id'])
        eq_(addon.support_email, data['support_email'])

    def test_wizard_step_1_required_paypal(self):
        url = self.addon.get_dev_url('market.1')
        data = {'paypal_id': '', 'support_email': 'a@a.com'}
        eq_(self.client.post(url, data).status_code, 200)

    @mock.patch('devhub.forms.PremiumForm.clean_paypal_id')
    def test_wizard_step_1_required_email(self, clean_paypal_id):
        url = self.addon.get_dev_url('market.1')
        data = {'paypal_id': 'a@a.com', 'support_email': ''}
        clean_paypal_id.return_value = data['support_email']
        eq_(self.client.post(url, data).status_code, 200)

    def test_wizard_step_2(self):
        self.price = Price.objects.create(price='0.99')
        url = self.addon.get_dev_url('market.2')
        eq_(self.client.post(url, {'price': self.price.pk}).status_code, 302)
        eq_(Addon.objects.get(pk=self.addon.pk).premium.price.pk,
            self.price.pk)

    def get_addon(self):
        return Addon.objects.get(pk=self.addon.pk)

    def add_addon_author(self, type):
        addon = Addon.objects.create(type=amo.ADDON_EXTENSION,
                                     premium_type=type)
        AddonUser.objects.create(addon=addon,
                                 user=self.addon.authors.all()[0])
        return addon

    def test_wizard_step_3(self):
        self.setup_premium()
        url = self.addon.get_dev_url('market.3')
        self.other_addon = self.add_addon_author(amo.ADDON_FREE)
        data = {
            'free': self.other_addon.pk,
            'do_upsell': 1,
            'text': 'some upsell',
        }
        eq_(self.client.post(url, data).status_code, 302)
        eq_(self.get_addon().upsold.free, self.other_addon)

    def test_form_only_free(self):
        self.premium = self.add_addon_author(amo.ADDON_PREMIUM)
        self.free = self.add_addon_author(amo.ADDON_FREE)
        url = self.addon.get_dev_url('market.3')
        res = self.client.get(url)
        upsell = res.context['form'].fields['free'].queryset.all()
        assert self.free in upsell
        assert self.premium not in upsell

    def test_wizard_no_free(self):
        self.price = Price.objects.create(price='0.99')
        url = self.addon.get_dev_url('market.2')
        res = self.client.post(url, {'price': self.price.pk})
        self.assertRedirects(res, self.addon.get_dev_url('market.4'))

    def test_wizard_step_4_failed(self):
        url = self.addon.get_dev_url('market.4')
        assert not self.get_addon().is_premium()
        eq_(self.client.post(url, {}).status_code, 302)
        assert not self.get_addon().is_premium()

    def test_wizard_step_4(self):
        self.setup_premium()
        self.addon.premium.update(paypal_permissions_token='foo')
        self.addon.update(premium_type=amo.ADDON_FREE)
        url = self.addon.get_dev_url('market.4')
        eq_(self.client.post(url, {}).status_code, 302)
        assert self.get_addon().is_premium()

    @mock.patch('addons.models.Addon.upsell')
    def test_wizard_step_4_fails(self, upsell):
        upsell.return_value = True
        url = self.addon.get_dev_url('market.4')
        eq_(self.client.post(url, {}).status_code, 403)
        assert not self.get_addon().is_premium()

    def test_wizard_step_4_status(self):
        self.setup_premium()
        self.addon.premium.update(paypal_permissions_token='foo')
        self.addon.update(status=amo.STATUS_UNREVIEWED)
        url = self.addon.get_dev_url('market.4')
        self.client.post(url, {})
        eq_(self.get_addon().status, amo.STATUS_NOMINATED)

    def test_logs(self):
        self.setup_premium()
        self.addon.premium.update(paypal_permissions_token='foo')
        url = self.addon.get_dev_url('market.4')
        eq_(self.client.post(url, {}).status_code, 302)
        eq_(ActivityLog.objects.for_addons(self.addon)[0].action,
            amo.LOG.MAKE_PREMIUM.id)

    def test_can_edit(self):
        self.setup_premium()
        assert 'no-edit' not in self.client.get(self.url).content

    def test_wizard_denied(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
        for x in xrange(1, 5):
            res = self.client.get(self.addon.get_dev_url('market.%s' % x))
            eq_(res.status_code, 403)

    def test_no_delete_link_premium_addon(self):
        self.setup_premium()
        doc = pq(self.client.get(self.addon.get_dev_url('versions')).content)
        eq_(len(doc('#delete-addon')), 0)

    def test_no_delete_premium_addon(self):
        self.setup_premium()
        res = self.client.post(self.addon.get_dev_url('delete'),
                               {'password': 'password'})
        eq_(res.status_code, 302)
        assert Addon.objects.filter(pk=self.addon.id).exists(), (
            "Unexpected: Addon should exist")


class TestIssueRefund(amo.tests.TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        waffle.models.Switch.objects.create(name='allow-refund', active=True)

        self.addon = Addon.objects.get(id=3615)
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
    def test_addons_issue(self, refund, enqueue_refund):
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
    def test_addons_decline(self, refund, enqueue_refund):
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
                r = Refund.objects.create(contribution=c, status=status,
                                          requested=datetime.now())
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

    @mock.patch.object(settings, 'TASK_USER_ID', 999)
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

    @mock.patch.object(settings, 'TASK_USER_ID', 999)
    def test_tables(self):
        self.generate_refunds()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('#enable-payments').length, 0)
        for key in self.queues.keys():
            table = doc('#queue-%s' % key)
            eq_(table.length, 1)

    @mock.patch.object(settings, 'TASK_USER_ID', 999)
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


class TestDelete(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.addon = self.get_addon()
        assert self.client.login(username='del@icio.us', password='password')
        self.url = self.addon.get_dev_url('delete')

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def test_post_not(self):
        r = self.client.post(self.url, follow=True)
        eq_(pq(r.content)('.notification-box').text(),
                          'Password was incorrect. Add-on was not deleted.')

    def test_post(self):
        r = self.client.post(self.url, dict(password='password'), follow=True)
        eq_(pq(r.content)('.notification-box').text(), 'Add-on deleted.')
        self.assertRaises(Addon.DoesNotExist, self.get_addon)


class TestHome(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.url = reverse('devhub.index')

    def get_pq(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        return pq(r.content)

    def test_editor_promo(self):
        eq_(self.get_pq()('#devhub-sidebar #editor-promo').length, 1)

    def test_no_editor_promo(self):
        Addon.objects.all().delete()
        # Regular users (non-devs) should not see this promo.
        eq_(self.get_pq()('#devhub-sidebar #editor-promo').length, 0)


class TestActivityFeed(amo.tests.TestCase):
    fixtures = ('base/apps', 'base/users', 'base/addon_3615')

    def setUp(self):
        super(TestActivityFeed, self).setUp()
        assert self.client.login(username='del@icio.us', password='password')

    def test_feed_for_all(self):
        r = self.client.get(reverse('devhub.feed_all'))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('header h2').text(), 'Recent Activity for My Add-ons')
        eq_(doc('#breadcrumbs li:eq(2)').text(), 'Recent Activity')

    def test_feed_for_addon(self):
        addon = Addon.objects.no_cache().get(id=3615)
        r = self.client.get(reverse('devhub.feed', args=[addon.slug]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('header h2').text(),
            'Recent Activity for %s' % addon.name)
        eq_(doc('#breadcrumbs li:eq(3)').text(),
            addon.slug)

    def test_feed_disabled(self):
        addon = Addon.objects.no_cache().get(id=3615)
        addon.update(status=amo.STATUS_DISABLED)
        r = self.client.get(reverse('devhub.feed', args=[addon.slug]))
        eq_(r.status_code, 200)

    def test_feed_disabled_anon(self):
        self.client.logout()
        addon = Addon.objects.no_cache().get(id=3615)
        r = self.client.get(reverse('devhub.feed', args=[addon.slug]))
        eq_(r.status_code, 302)

    def add_hidden_log(self, action=amo.LOG.COMMENT_VERSION):
        addon = Addon.objects.get(id=3615)
        amo.set_user(UserProfile.objects.get(email='del@icio.us'))
        amo.log(action, addon, addon.versions.all()[0])
        return addon

    def test_feed_hidden(self):
        addon = self.add_hidden_log()
        self.add_hidden_log(amo.LOG.OBJECT_ADDED)
        res = self.client.get(reverse('devhub.feed', args=[addon.slug]))
        doc = pq(res.content)
        eq_(len(doc('#recent-activity p')), 1)

    def test_addons_hidden(self):
        self.add_hidden_log()
        self.add_hidden_log(amo.LOG.OBJECT_ADDED)
        res = self.client.get(reverse('devhub.addons'))
        doc = pq(res.content)
        eq_(len(doc('#dashboard-sidebar div.recent-activity li.item')), 0)


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
        eq_(doc('#status-bar button').text(), 'Remove Both')

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

    def test_with_contributions_labels(self):
        self.enable_addon_contributions()
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('label[for=the_reason] .req').length, (
               'the_reason field should be required.')
        assert doc('label[for=the_future] .req').length, (
               'the_future field should be required.')

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


class TestSubmitBase(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/addon_5579', 'base/users']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')
        self.addon = self.get_addon()

    def get_addon(self):
        return Addon.objects.no_cache().get(pk=3615)

    def get_version(self):
        return self.get_addon().versions.get()

    def get_step(self):
        return SubmitStep.objects.get(addon=self.get_addon())


class TestSubmitStep1(TestSubmitBase):

    def test_step1_submit(self):
        response = self.client.get(reverse('devhub.submit.1'))
        eq_(response.status_code, 200)
        doc = pq(response.content)
        eq_(doc('#breadcrumbs a').eq(1).attr('href'), reverse('devhub.addons'))
        links = doc('#agreement-container a')
        assert links
        for ln in links:
            href = ln.attrib['href']
            assert not href.startswith('%'), (
                "Looks like link %r to %r is still a placeholder" %
                (href, ln.text))


class TestSubmitStep2(amo.tests.TestCase):
    # More tests in TestCreateAddon.
    fixtures = ['base/users']

    def setUp(self):
        self.client.login(username='regular@mozilla.com', password='password')

    def test_step_2_with_cookie(self):
        r = self.client.post(reverse('devhub.submit.1'))
        self.assertRedirects(r, reverse('devhub.submit.2'))
        r = self.client.get(reverse('devhub.submit.2'))
        eq_(r.status_code, 200)

    def test_step_2_no_cookie(self):
        # We require a cookie that gets set in step 1.
        r = self.client.get(reverse('devhub.submit.2'), follow=True)
        self.assertRedirects(r, reverse('devhub.submit.1'))


class TestSubmitStep3(TestSubmitBase):

    def setUp(self):
        super(TestSubmitStep3, self).setUp()
        self.url = reverse('devhub.submit.3', args=['a3615'])
        SubmitStep.objects.create(addon_id=3615, step=3)
        cron.build_reverse_name_lookup()

        AddonCategory.objects.filter(addon=self.get_addon(),
                category=Category.objects.get(id=23)).delete()
        AddonCategory.objects.filter(addon=self.get_addon(),
                category=Category.objects.get(id=24)).delete()

        ctx = self.client.get(self.url).context['cat_form']
        self.cat_initial = initial(ctx.initial_forms[0])

    def get_dict(self, **kw):
        cat_initial = kw.pop('cat_initial', self.cat_initial)
        fs = formset(cat_initial, initial_count=1)
        result = {'name': 'Test name', 'slug': 'testname',
                  'description': 'desc', 'summary': 'Hello!'}
        result.update(**kw)
        result.update(fs)
        return result

    def test_submit_success(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

        # Post and be redirected.
        d = self.get_dict()
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        eq_(self.get_step().step, 4)

        addon = self.get_addon()
        eq_(addon.name, 'Test name')
        eq_(addon.slug, 'testname')
        eq_(addon.description, 'desc')
        eq_(addon.summary, 'Hello!')
        # Test add-on log activity.
        log_items = ActivityLog.objects.for_addons(addon)
        assert not log_items.filter(action=amo.LOG.EDIT_DESCRIPTIONS.id), (
                "Creating a description needn't be logged.")

    def test_submit_name_unique(self):
        # Make sure name is unique.
        r = self.client.post(self.url, self.get_dict(name='Cooliris'))
        error = 'This name is already in use. Please choose another.'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_name_unique_strip(self):
        # Make sure we can't sneak in a name by adding a space or two.
        r = self.client.post(self.url, self.get_dict(name='  Cooliris  '))
        error = 'This name is already in use. Please choose another.'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_name_unique_case(self):
        # Make sure unique names aren't case sensitive.
        r = self.client.post(self.url, self.get_dict(name='cooliris'))
        error = 'This name is already in use. Please choose another.'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_name_length(self):
        # Make sure the name isn't too long.
        d = self.get_dict(name='a' * 51)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        error = 'Ensure this value has at most 50 characters (it has 51).'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_slug_invalid(self):
        # Submit an invalid slug.
        d = self.get_dict(slug='slug!!! aksl23%%')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'slug', "Enter a valid 'slug' " +
                    "consisting of letters, numbers, underscores or hyphens.")

    def test_submit_slug_required(self):
        # Make sure the slug is required.
        r = self.client.post(self.url, self.get_dict(slug=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'slug', 'This field is required.')

    def test_submit_summary_required(self):
        # Make sure summary is required.
        r = self.client.post(self.url, self.get_dict(summary=''))
        eq_(r.status_code, 200)
        self.assertFormError(r, 'form', 'summary', 'This field is required.')

    def test_submit_summary_length(self):
        # Summary is too long.
        r = self.client.post(self.url, self.get_dict(summary='a' * 251))
        eq_(r.status_code, 200)
        error = 'Ensure this value has at most 250 characters (it has 251).'
        self.assertFormError(r, 'form', 'summary', error)

    def test_submit_categories_required(self):
        del self.cat_initial['categories']
        r = self.client.post(self.url,
                             self.get_dict(cat_initial=self.cat_initial))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['This field is required.'])

    def test_submit_categories_max(self):
        eq_(amo.MAX_CATEGORIES, 2)
        self.cat_initial['categories'] = [22, 23, 24]
        r = self.client.post(self.url,
                             self.get_dict(cat_initial=self.cat_initial))
        eq_(r.context['cat_form'].errors[0]['categories'],
            ['You can have only 2 categories.'])

    def test_submit_categories_add(self):
        eq_([c.id for c in self.get_addon().all_categories], [22])
        self.cat_initial['categories'] = [22, 23]

        self.client.post(self.url, self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        eq_(sorted(addon_cats), [22, 23])

    def test_submit_categories_addandremove(self):
        AddonCategory(addon=self.addon, category_id=23).save()
        eq_([c.id for c in self.get_addon().all_categories], [22, 23])

        self.cat_initial['categories'] = [22, 24]
        self.client.post(self.url, self.get_dict(cat_initial=self.cat_initial))
        category_ids_new = [c.id for c in self.get_addon().all_categories]
        eq_(category_ids_new, [22, 24])

    def test_submit_categories_remove(self):
        c = Category.objects.get(id=23)
        AddonCategory(addon=self.addon, category=c).save()
        eq_([c.id for c in self.get_addon().all_categories], [22, 23])

        self.cat_initial['categories'] = [22]
        self.client.post(self.url, self.get_dict(cat_initial=self.cat_initial))
        category_ids_new = [c.id for c in self.get_addon().all_categories]
        eq_(category_ids_new, [22])

    def test_check_version(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        version = doc("#current_version").val()

        eq_(version, self.addon.current_version.version)


class TestSubmitStep4(TestSubmitBase):

    def setUp(self):
        super(TestSubmitStep4, self).setUp()
        self.old_addon_icon_url = settings.ADDON_ICON_URL
        settings.ADDON_ICON_URL = (settings.STATIC_URL +
            '/img/uploads/addon_icons/%s/%s-%s.png?modified=%s')
        SubmitStep.objects.create(addon_id=3615, step=4)
        self.url = reverse('devhub.submit.4', args=['a3615'])
        self.next_step = reverse('devhub.submit.5', args=['a3615'])
        self.icon_upload = reverse('devhub.addons.upload_icon',
                                   args=['a3615'])
        self.preview_upload = reverse('devhub.addons.upload_preview',
                                      args=['a3615'])

    def tearDown(self):
        settings.ADDON_ICON_URL = self.old_addon_icon_url

    def test_get(self):
        eq_(self.client.get(self.url).status_code, 200)

    def test_post(self):
        data = dict(icon_type='')
        data_formset = self.formset_media(**data)
        r = self.client.post(self.url, data_formset)
        eq_(r.status_code, 302)
        eq_(self.get_step().step, 5)

    def formset_new_form(self, *args, **kw):
        ctx = self.client.get(self.url).context

        blank = initial(ctx['preview_form'].forms[-1])
        blank.update(**kw)
        return blank

    def formset_media(self, *args, **kw):
        kw.setdefault('initial_count', 0)
        kw.setdefault('prefix', 'files')

        fs = formset(*[a for a in args] + [self.formset_new_form()], **kw)
        return dict([(k, '' if v is None else v) for k, v in fs.items()])

    def test_icon_upload_attributes(self):
        doc = pq(self.client.get(self.url).content)
        field = doc('input[name=icon_upload]')
        eq_(field.length, 1)
        eq_(sorted(field.attr('data-allowed-types').split('|')),
            ['image/jpeg', 'image/png'])
        eq_(field.attr('data-upload-url'), self.icon_upload)

    def test_edit_media_defaulticon(self):
        data = dict(icon_type='')
        data_formset = self.formset_media(**data)

        self.client.post(self.url, data_formset)

        addon = self.get_addon()

        assert addon.get_icon_url(64).endswith('icons/default-64.png')

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_media_preuploadedicon(self):
        data = dict(icon_type='icon/appearance')
        data_formset = self.formset_media(**data)
        self.client.post(self.url, data_formset)

        addon = self.get_addon()

        eq_('/'.join(addon.get_icon_url(64).split('/')[-2:]),
            'addon-icons/appearance-64.png')

        for k in data:
            eq_(unicode(getattr(addon, k)), data[k])

    def test_edit_media_uploadedicon(self):
        img = get_image_path('mozilla.png')
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = dict(icon_type='image/png',
                    icon_upload_hash=response_json['upload_hash'])
        data_formset = self.formset_media(**data)

        self.client.post(self.url, data_formset)

        addon = self.get_addon()

        # Sad we're hardcoding /3/ here, but that's how the URLs work
        _url = addon.get_icon_url(64).split('?')[0]
        assert _url.endswith('img/uploads/addon_icons/3/%s-64.png' % addon.id)

        eq_(data['icon_type'], 'image/png')

        # Check that it was actually uploaded
        dirname = os.path.join(settings.ADDON_ICONS_PATH,
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-32.png' % addon.id)

        assert storage.exists(dest)

        eq_(Image.open(storage.open(dest)).size, (32, 12))

    def test_edit_media_uploadedicon_noresize(self):
        img = "%s/img/notifications/error.png" % settings.MEDIA_ROOT
        src_image = open(img, 'rb')

        data = dict(upload_image=src_image)

        response = self.client.post(self.icon_upload, data)
        response_json = json.loads(response.content)
        addon = self.get_addon()

        # Now, save the form so it gets moved properly.
        data = dict(icon_type='image/png',
                    icon_upload_hash=response_json['upload_hash'])
        data_formset = self.formset_media(**data)

        self.client.post(self.url, data_formset)
        addon = self.get_addon()

        # Sad we're hardcoding /3/ here, but that's how the URLs work
        _url = addon.get_icon_url(64).split('?')[0]
        assert _url.endswith('img/uploads/addon_icons/3/%s-64.png' % addon.id)

        eq_(data['icon_type'], 'image/png')

        # Check that it was actually uploaded
        dirname = os.path.join(settings.ADDON_ICONS_PATH,
                               '%s' % (addon.id / 1000))
        dest = os.path.join(dirname, '%s-64.png' % addon.id)

        assert storage.exists(dest)

        eq_(Image.open(storage.open(dest)).size, (48, 48))

    def test_client_lied(self):
        filehandle = open(get_image_path('non-animated.gif'), 'rb')

        data = {'upload_image': filehandle}

        res = self.client.post(self.preview_upload, data)
        response_json = json.loads(res.content)

        eq_(response_json['errors'][0], u'Images must be either PNG or JPG.')

    def test_icon_animated(self):
        filehandle = open(get_image_path('animated.png'), 'rb')
        data = {'upload_image': filehandle}

        res = self.client.post(self.preview_upload, data)
        response_json = json.loads(res.content)

        eq_(response_json['errors'][0], u'Images cannot be animated.')

    def test_icon_non_animated(self):
        filehandle = open(get_image_path('non-animated.png'), 'rb')
        data = {'icon_type': 'image/png', 'icon_upload': filehandle}
        data_formset = self.formset_media(**data)
        res = self.client.post(self.url, data_formset)
        eq_(res.status_code, 302)
        eq_(self.get_step().step, 5)


class Step5TestBase(TestSubmitBase):

    def setUp(self):
        super(Step5TestBase, self).setUp()
        SubmitStep.objects.create(addon_id=self.addon.id, step=5)
        self.url = reverse('devhub.submit.5', args=['a3615'])
        self.next_step = reverse('devhub.submit.6', args=['a3615'])
        License.objects.create(builtin=3, on_form=True)


class TestSubmitStep5(Step5TestBase):
    """License submission."""

    def test_get(self):
        eq_(self.client.get(self.url).status_code, 200)

    def test_set_license(self):
        r = self.client.post(self.url, {'builtin': 3})
        self.assertRedirects(r, self.next_step)
        eq_(self.get_addon().current_version.license.builtin, 3)
        eq_(self.get_step().step, 6)
        log_items = ActivityLog.objects.for_addons(self.get_addon())
        assert not log_items.filter(action=amo.LOG.CHANGE_LICENSE.id), (
                "Initial license choice:6 needn't be logged.")

    def test_license_error(self):
        r = self.client.post(self.url, {'builtin': 4})
        eq_(r.status_code, 200)
        self.assertFormError(r, 'license_form', 'builtin',
                             'Select a valid choice. 4 is not one of '
                             'the available choices.')
        eq_(self.get_step().step, 5)

    def test_set_eula(self):
        self.get_addon().update(eula=None, privacy_policy=None)
        r = self.client.post(self.url, dict(builtin=3, has_eula=True,
                                            eula='xxx'))
        self.assertRedirects(r, self.next_step)
        eq_(unicode(self.get_addon().eula), 'xxx')
        eq_(self.get_step().step, 6)

    def test_set_eula_nomsg(self):
        """
        You should not get punished with a 500 for not writing your EULA...
        but perhaps you should feel shame for lying to us.  This test does not
        test for shame.
        """
        self.get_addon().update(eula=None, privacy_policy=None)
        r = self.client.post(self.url, dict(builtin=3, has_eula=True))
        self.assertRedirects(r, self.next_step)
        eq_(self.get_step().step, 6)


class TestSubmitStep6(TestSubmitBase):

    def setUp(self):
        super(TestSubmitStep6, self).setUp()
        SubmitStep.objects.create(addon_id=3615, step=6)
        self.url = reverse('devhub.submit.6', args=['a3615'])

    def test_get(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_require_review_type(self):
        r = self.client.post(self.url, {'dummy': 'text'})
        eq_(r.status_code, 200)
        self.assertFormError(r, 'review_type_form', 'review_type',
                             'A review type must be selected.')

    def test_bad_review_type(self):
        d = dict(review_type='jetsfool')
        r = self.client.post(self.url, d)
        eq_(r.status_code, 200)
        self.assertFormError(r, 'review_type_form', 'review_type',
                             'Select a valid choice. jetsfool is not one of '
                             'the available choices.')

    def test_prelim_review(self):
        d = dict(review_type=amo.STATUS_UNREVIEWED)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        eq_(self.get_addon().status, amo.STATUS_UNREVIEWED)
        assert_raises(SubmitStep.DoesNotExist, self.get_step)

    def test_full_review(self):
        self.get_version().update(nomination=None)
        d = dict(review_type=amo.STATUS_NOMINATED)
        r = self.client.post(self.url, d)
        eq_(r.status_code, 302)
        addon = self.get_addon()
        eq_(addon.status, amo.STATUS_NOMINATED)
        assert close_to_now(self.get_version().nomination)
        assert_raises(SubmitStep.DoesNotExist, self.get_step)

    def test_nomination_date_is_only_set_once(self):
        # This was a regression, see bug 632191.
        # Nominate:
        r = self.client.post(self.url, dict(review_type=amo.STATUS_NOMINATED))
        eq_(r.status_code, 302)
        nomdate = datetime.now() - timedelta(days=5)
        self.get_version().update(nomination=nomdate, _signal=False)
        # Update something else in the addon:
        self.get_addon().update(slug='foobar')
        eq_(self.get_version().nomination.timetuple()[0:5],
            nomdate.timetuple()[0:5])


class TestSubmitStep7(TestSubmitBase):

    def setUp(self):
        super(TestSubmitStep7, self).setUp()
        self.url = reverse('devhub.submit.7', args=[self.addon.slug])

    def test_finish_submitting_addon(self):
        eq_(self.addon.current_version.supported_platforms, [amo.PLATFORM_ALL])

        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)

        a = doc('a#submitted-addon-url')
        url = self.addon.get_url_path()
        eq_(a.attr('href'), url)
        eq_(a.text(), absolutify(url))

        next_steps = doc('.done-next-steps li a')

        # edit listing of freshly submitted add-on...
        eq_(next_steps.eq(0).attr('href'), self.addon.get_dev_url())

        # edit your developer profile...
        eq_(next_steps.eq(1).attr('href'), self.addon.get_dev_url('profile'))

    def test_finish_submitting_platform_specific_addon(self):
        # mac-only Add-on:
        addon = Addon.objects.get(name__localized_string='Cooliris')
        AddonUser.objects.create(user=UserProfile.objects.get(pk=55021),
                                 addon=addon)
        r = self.client.get(reverse('devhub.submit.7', args=[addon.slug]))
        eq_(r.status_code, 200)
        next_steps = pq(r.content)('.done-next-steps li a')

        # upload more platform specific files...
        eq_(next_steps.eq(0).attr('href'),
            reverse('devhub.versions.edit',
                    kwargs=dict(addon_id=addon.slug,
                                version_id=addon.current_version.id)))

        # edit listing of freshly submitted add-on...
        eq_(next_steps.eq(1).attr('href'), addon.get_dev_url())

    def test_finish_addon_for_prelim_review(self):
        self.addon.update(status=amo.STATUS_UNREVIEWED)

        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        doc = pq(response.content)
        intro = doc('.addon-submission-process p').text().strip()
        assert 'Preliminary Review' in intro, ('Unexpected intro: %s' % intro)

    def test_finish_addon_for_full_review(self):
        self.addon.update(status=amo.STATUS_NOMINATED)

        response = self.client.get(self.url)
        eq_(response.status_code, 200)
        doc = pq(response.content)
        intro = doc('.addon-submission-process p').text().strip()
        assert 'Full Review' in intro, ('Unexpected intro: %s' % intro)

    def test_incomplete_addon_no_versions(self):
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.versions.all().delete()
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, self.addon.get_dev_url('versions'), 302)

    def test_link_to_activityfeed(self):
        r = self.client.get(self.url, follow=True)
        doc = pq(r.content)
        eq_(doc('.done-next-steps a').eq(2).attr('href'),
            reverse('devhub.feed', args=[self.addon.slug]))

    def test_display_non_ascii_url(self):
        u = 'フォクすけといっしょ'
        self.addon.update(slug=u)
        r = self.client.get(reverse('devhub.submit.7', args=[u]))
        eq_(r.status_code, 200)
        # The meta charset will always be utf-8.
        doc = pq(r.content.decode('utf-8'))
        eq_(doc('#submitted-addon-url').text(),
            u'%s/en-US/firefox/addon/%s/' % (
                settings.SITE_URL, u.decode('utf8')))

    def test_addon_editor_pitch(self):
        res = self.client.get(self.url)
        eq_(pq(res.content)('#editor-pitch').length, 1)


class TestResumeStep(TestSubmitBase):

    def setUp(self):
        super(TestResumeStep, self).setUp()
        self.url = reverse('devhub.submit.resume', args=['a3615'])

    def test_no_step_redirect(self):
        r = self.client.get(self.url, follow=True)
        self.assertRedirects(r, self.addon.get_dev_url('versions'), 302)

    def test_step_redirects(self):
        SubmitStep.objects.create(addon_id=3615, step=1)
        for i in xrange(3, 7):
            SubmitStep.objects.filter(addon=self.get_addon()).update(step=i)
            r = self.client.get(self.url, follow=True)
            self.assertRedirects(r, reverse('devhub.submit.%s' % i,
                                            args=['a3615']))

    def test_redirect_from_other_pages(self):
        SubmitStep.objects.create(addon_id=3615, step=4)
        r = self.client.get(reverse('devhub.addons.edit', args=['a3615']),
                            follow=True)
        self.assertRedirects(r, reverse('devhub.submit.4', args=['a3615']))


class TestSubmitBump(TestSubmitBase):

    def setUp(self):
        super(TestSubmitBump, self).setUp()
        self.url = reverse('devhub.submit.bump', args=['a3615'])

    def test_bump_acl(self):
        r = self.client.post(self.url, {'step': 4})
        eq_(r.status_code, 403)

    def test_bump_submit_and_redirect(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        r = self.client.post(self.url, {'step': 4}, follow=True)
        self.assertRedirects(r, reverse('devhub.submit.4', args=['a3615']))
        eq_(self.get_step().step, 4)


class TestSubmitSteps(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        assert self.client.login(username='del@icio.us', password='password')

    def assert_linked(self, doc, numbers):
        """Check that the nth <li> in the steps list is a link."""
        lis = doc('.submit-addon-progress li')
        eq_(len(lis), 7)
        for idx, li in enumerate(lis):
            links = pq(li)('a')
            if (idx + 1) in numbers:
                eq_(len(links), 1)
            else:
                eq_(len(links), 0)

    def assert_highlight(self, doc, num):
        """Check that the nth <li> is marked as .current."""
        lis = doc('.submit-addon-progress li')
        assert pq(lis[num - 1]).hasClass('current')
        eq_(len(pq('.current', lis)), 1)

    def test_step_1(self):
        r = self.client.get(reverse('devhub.submit.1'))
        eq_(r.status_code, 200)

    def test_on_step_6(self):
        # Hitting the step we're supposed to be on is a 200.
        SubmitStep.objects.create(addon_id=3615, step=6)
        r = self.client.get(reverse('devhub.submit.6',
                                    args=['a3615']))
        eq_(r.status_code, 200)

    def test_skip_step_6(self):
        # We get bounced back to step 3.
        SubmitStep.objects.create(addon_id=3615, step=3)
        r = self.client.get(reverse('devhub.submit.6',
                                    args=['a3615']), follow=True)
        self.assertRedirects(r, reverse('devhub.submit.3', args=['a3615']))

    def test_all_done(self):
        # There's no SubmitStep, so we must be done.
        r = self.client.get(reverse('devhub.submit.6',
                                    args=['a3615']), follow=True)
        self.assertRedirects(r, reverse('devhub.submit.7', args=['a3615']))

    def test_menu_step_1(self):
        doc = pq(self.client.get(reverse('devhub.submit.1')).content)
        self.assert_linked(doc, [1])
        self.assert_highlight(doc, 1)

    def test_menu_step_2(self):
        self.client.post(reverse('devhub.submit.1'))
        doc = pq(self.client.get(reverse('devhub.submit.2')).content)
        self.assert_linked(doc, [1, 2])
        self.assert_highlight(doc, 2)

    def test_menu_step_3(self):
        SubmitStep.objects.create(addon_id=3615, step=3)
        url = reverse('devhub.submit.3', args=['a3615'])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [3])
        self.assert_highlight(doc, 3)

    def test_menu_step_3_from_6(self):
        SubmitStep.objects.create(addon_id=3615, step=6)
        url = reverse('devhub.submit.3', args=['a3615'])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [3, 4, 5, 6])
        self.assert_highlight(doc, 3)

    def test_menu_step_6(self):
        SubmitStep.objects.create(addon_id=3615, step=6)
        url = reverse('devhub.submit.6', args=['a3615'])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [3, 4, 5, 6])
        self.assert_highlight(doc, 6)

    def test_menu_step_7(self):
        url = reverse('devhub.submit.7', args=['a3615'])
        doc = pq(self.client.get(url).content)
        self.assert_linked(doc, [])
        self.assert_highlight(doc, 7)


class TestUpload(BaseUploadTest):
    fixtures = ['base/apps', 'base/users']

    def setUp(self):
        super(TestUpload, self).setUp()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.url = reverse('devhub.upload')

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
        eq_(msg['message'], u'The package is not of a recognized type.')
        eq_(msg['description'], u'')

    def test_redirect(self):
        r = self.post()
        upload = FileUpload.objects.get()
        url = reverse('devhub.upload_detail', args=[upload.pk, 'json'])
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
        return self.client.post(reverse('devhub.upload'), {'upload': data})

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

    def upload_file(self, file):
        addon = os.path.join(settings.ROOT, 'apps', 'devhub', 'tests',
                             'addons', file)
        with open(addon, 'rb') as f:
            r = self.client.post(reverse('devhub.upload'),
                                 {'upload': f})
        eq_(r.status_code, 302)

    @attr('validator')
    def test_detail_json(self):
        self.post()

        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid, 'json']))
        eq_(r.status_code, 200)
        data = json.loads(r.content)
        assert_no_validation_errors(data)
        eq_(data['url'],
            reverse('devhub.upload_detail', args=[upload.uuid, 'json']))
        eq_(data['full_report_url'],
            reverse('devhub.upload_detail', args=[upload.uuid]))
        # We must have tiers
        assert len(data['validation']['messages'])
        msg = data['validation']['messages'][0]
        eq_(msg['tier'], 1)

    def test_detail_view(self):
        self.post()
        upload = FileUpload.objects.get(name='animated.png')
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid]))
        eq_(r.status_code, 200)
        doc = pq(r.content)
        eq_(doc('header h2').text(), 'Validation Results for animated.png')
        suite = doc('#addon-validator-suite')
        eq_(suite.attr('data-validateurl'),
            reverse('devhub.standalone_upload_detail', args=[upload.uuid]))

    @mock.patch('devhub.tasks.run_validator')
    def check_excluded_platforms(self, xpi, platforms, v):
        v.return_value = json.dumps(self.validation_ok())
        self.upload_file(xpi)
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
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

    @mock.patch('devhub.tasks.run_validator')
    @mock.patch.object(waffle, 'flag_is_active')
    def test_unparsable_xpi(self, flag_is_active, v):
        flag_is_active.return_value = True
        v.return_value = json.dumps(self.validation_ok())
        self.upload_file('unopenable.xpi')
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
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


class UploadTest(BaseUploadTest, amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        super(UploadTest, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.addon.update(guid='guid@xpi')
        if not Platform.objects.filter(id=amo.PLATFORM_MAC.id):
            Platform.objects.create(id=amo.PLATFORM_MAC.id)
        assert self.client.login(username='del@icio.us', password='password')


class TestQueuePosition(UploadTest):
    fixtures = ['base/apps', 'base/users',
                'base/addon_3615', 'base/platforms']

    def setUp(self):
        super(TestQueuePosition, self).setUp()

        self.url = reverse('devhub.versions.add_file',
                           args=[self.addon.slug, self.version.id])
        self.edit_url = reverse('devhub.versions.edit',
                                args=[self.addon.slug, self.version.id])
        version_files = self.version.files.all()[0]
        version_files.platform_id = amo.PLATFORM_LINUX.id
        version_files.save()

    def test_not_in_queue(self):
        r = self.client.get(self.addon.get_dev_url('versions'))

        eq_(self.addon.status, amo.STATUS_PUBLIC)
        eq_(pq(r.content)('.version-status-actions .dark').length, 0)

    def test_in_queue(self):
        statuses = [(amo.STATUS_NOMINATED, amo.STATUS_NOMINATED),
                    (amo.STATUS_PUBLIC, amo.STATUS_UNREVIEWED),
                    (amo.STATUS_LITE, amo.STATUS_UNREVIEWED)]

        for addon_status in statuses:
            self.addon.status = addon_status[0]
            self.addon.save()

            file = self.addon.latest_version.files.all()[0]
            file.status = addon_status[1]
            file.save()

            r = self.client.get(self.addon.get_dev_url('versions'))
            doc = pq(r.content)

            span = doc('.version-status-actions .dark')

            eq_(span.length, 1)
            assert "Queue Position: 1 of 1" in span.text()


class TestVersionAddFile(UploadTest):
    fixtures = ['base/apps', 'base/users',
                'base/addon_3615', 'base/platforms']

    def setUp(self):
        super(TestVersionAddFile, self).setUp()
        self.version.update(version='0.1')
        self.url = reverse('devhub.versions.add_file',
                           args=[self.addon.slug, self.version.id])
        self.edit_url = reverse('devhub.versions.edit',
                                args=[self.addon.slug, self.version.id])
        version_files = self.version.files.all()[0]
        version_files.platform_id = amo.PLATFORM_LINUX.id
        version_files.save()

    def make_mobile(self):
        app = Application.objects.get(pk=amo.MOBILE.id)
        for a in self.version.apps.all():
            a.application = app
            a.save()

    def post(self, platform=amo.PLATFORM_MAC):
        return self.client.post(self.url, dict(upload=self.upload.pk,
                                               platform=platform.id))

    def test_guid_matches(self):
        self.addon.update(guid='something.different')
        r = self.post()
        assert_json_error(r, None, "UUID doesn't match add-on.")

    def test_version_matches(self):
        self.version.update(version='2.0')
        r = self.post()
        assert_json_error(r, None, "Version doesn't match")

    def test_delete_button_enabled(self):
        version = self.addon.current_version
        version.files.all()[0].update(status=amo.STATUS_UNREVIEWED)

        r = self.client.get(self.edit_url)
        doc = pq(r.content)('#file-list')
        eq_(doc.find('a.remove').length, 1)
        eq_(doc.find('span.remove.tooltip').length, 0)

    def test_delete_button_disabled(self):
        r = self.client.get(self.edit_url)
        doc = pq(r.content)('#file-list')
        eq_(doc.find('a.remove').length, 0)
        eq_(doc.find('span.remove.tooltip').length, 1)

        tip = doc.find('span.remove.tooltip')
        assert "You cannot remove an individual file" in tip.attr('title')

    def test_delete_button_multiple(self):
        file = self.addon.current_version.files.all()[0]
        file.pk = None
        file.save()

        cases = [(amo.STATUS_UNREVIEWED, amo.STATUS_UNREVIEWED, True),
                 (amo.STATUS_LISTED, amo.STATUS_UNREVIEWED, False),
                 (amo.STATUS_LISTED, amo.STATUS_LISTED, False)]

        for c in cases:
            version_files = self.addon.current_version.files.all()
            version_files[0].update(status=c[0])
            version_files[1].update(status=c[1])

            r = self.client.get(self.edit_url)
            doc = pq(r.content)('#file-list')

            assert (doc.find('a.remove').length > 0) == c[2]
            assert not (doc.find('span.remove').length > 0) == c[2]

            if not c[2]:
                tip = doc.find('span.remove.tooltip')
                assert "You cannot remove an individual" in tip.attr('title')

    def test_delete_submit_disabled(self):
        file_id = self.addon.current_version.files.all()[0].id
        platform = amo.PLATFORM_MAC.id
        form = {'DELETE': 'checked', 'id': file_id, 'platform': platform}

        data = formset(form, platform=platform, upload=self.upload.pk,
                       initial_count=1, prefix='files')

        r = self.client.post(self.edit_url, data)
        doc = pq(r.content)

        assert "You cannot delete a file once" in doc('.errorlist li').text()

    def test_delete_submit_enabled(self):
        version = self.addon.current_version
        version.files.all()[0].update(status=amo.STATUS_UNREVIEWED)

        file_id = self.addon.current_version.files.all()[0].id
        platform = amo.PLATFORM_MAC.id
        form = {'DELETE': 'checked', 'id': file_id, 'platform': platform}

        data = formset(form, platform=platform, upload=self.upload.pk,
                       initial_count=1, prefix='files')
        data.update(formset(total_count=1, initial_count=1))

        r = self.client.post(self.edit_url, data)
        doc = pq(r.content)

        eq_(doc('.errorlist li').length, 0)

    def test_platform_limits(self):
        r = self.post(platform=amo.PLATFORM_BSD)
        assert_json_error(r, 'platform',
                               'Select a valid choice. That choice is not '
                               'one of the available choices.')

    def test_platform_choices(self):
        r = self.client.get(self.edit_url)
        form = r.context['new_file_form']
        platform = self.version.files.get().platform_id
        choices = form.fields['platform'].choices
        # User cannot upload existing platforms:
        assert platform not in dict(choices), choices
        # User cannot upload platform=ALL when platform files exist.
        assert amo.PLATFORM_ALL.id not in dict(choices), choices

    def test_platform_choices_when_no_files(self):
        all_choices = self.version.compatible_platforms().values()
        self.version.files.all().delete()
        url = reverse('devhub.versions.edit',
                      args=[self.addon.slug, self.version.id])
        r = self.client.get(url)
        form = r.context['new_file_form']
        eq_(sorted(dict(form.fields['platform'].choices).keys()),
            sorted([p.id for p in all_choices]))

    def test_platform_choices_when_mobile(self):
        self.make_mobile()
        self.version.files.all().delete()
        r = self.client.get(self.edit_url)
        form = r.context['new_file_form']
        # TODO(Kumar) Allow All Mobile Platforms when supported for downloads.
        # See bug 646268.
        exp_plats = (set(amo.MOBILE_PLATFORMS.values()) -
                     set([amo.PLATFORM_ALL_MOBILE]))
        eq_(sorted([unicode(c[1]) for c in form.fields['platform'].choices]),
            sorted([unicode(p.name) for p in exp_plats]))

    def test_exclude_mobile_all_when_we_have_platform_files(self):
        self.make_mobile()
        # set one to Android
        self.version.files.all().update(platform=amo.PLATFORM_ANDROID.id)
        r = self.post(platform=amo.PLATFORM_ALL_MOBILE)
        assert_json_error(r, 'platform',
                          'Select a valid choice. That choice is not '
                          'one of the available choices.')

    def test_type_matches(self):
        self.addon.update(type=amo.ADDON_THEME)
        r = self.post()
        assert_json_error(r, None, "<em:type> doesn't match add-on")

    def test_file_platform(self):
        # Check that we're creating a new file with the requested platform.
        qs = self.version.files
        eq_(len(qs.all()), 1)
        assert not qs.filter(platform=amo.PLATFORM_MAC.id)
        self.post()
        eq_(len(qs.all()), 2)
        assert qs.get(platform=amo.PLATFORM_MAC.id)

    def test_upload_not_found(self):
        r = self.client.post(self.url, dict(upload='xxx',
                                            platform=amo.PLATFORM_MAC.id))
        assert_json_error(r, 'upload',
                               'There was an error with your upload. '
                               'Please try again.')

    @mock.patch('versions.models.Version.is_allowed_upload')
    def test_cant_upload(self, allowed):
        """Test that if is_allowed_upload fails, the upload will fail."""
        allowed.return_value = False
        res = self.post()
        assert_json_error(res, '__all__',
                          'You cannot upload any more files for this version.')

    def test_success_html(self):
        r = self.post()
        eq_(r.status_code, 200)
        new_file = self.version.files.get(platform=amo.PLATFORM_MAC.id)
        eq_(r.context['form'].instance, new_file)

    def test_show_item_history(self):
        version = self.addon.current_version
        user = UserProfile.objects.get(email='editor@mozilla.com')

        details = {'comments': 'yo', 'files': [version.files.all()[0].id]}
        amo.log(amo.LOG.APPROVE_VERSION, self.addon,
                self.addon.current_version, user=user, created=datetime.now(),
                details=details)

        doc = pq(self.client.get(self.edit_url).content)
        appr = doc('#approval_status')

        eq_(appr.length, 1)
        eq_(appr.find('strong').eq(0).text(), "File  (Linux)")
        eq_(appr.find('.version-comments').length, 1)

        comment = appr.find('.version-comments').eq(0)
        eq_(comment.find('strong a').text(), "Delicious Bookmarks Version 0.1")
        eq_(comment.find('div.email_comment').length, 1)
        eq_(comment.find('div').eq(1).text(), "yo")

    def test_show_item_history_hide_message(self):
        """ Test to make sure comments not to the user aren't shown. """
        version = self.addon.current_version
        user = UserProfile.objects.get(email='editor@mozilla.com')

        details = {'comments': 'yo', 'files': [version.files.all()[0].id]}
        amo.log(amo.LOG.REQUEST_SUPER_REVIEW, self.addon,
                self.addon.current_version, user=user, created=datetime.now(),
                details=details)

        doc = pq(self.client.get(self.edit_url).content)
        comment = doc('#approval_status').find('.version-comments').eq(0)

        eq_(comment.find('div.email_comment').length, 0)

    def test_show_item_history_multiple(self):
        version = self.addon.current_version
        user = UserProfile.objects.get(email='editor@mozilla.com')

        details = {'comments': 'yo', 'files': [version.files.all()[0].id]}
        amo.log(amo.LOG.APPROVE_VERSION, self.addon,
                self.addon.current_version, user=user, created=datetime.now(),
                details=details)

        amo.log(amo.LOG.REQUEST_SUPER_REVIEW, self.addon,
                self.addon.current_version, user=user, created=datetime.now(),
                details=details)

        doc = pq(self.client.get(self.edit_url).content)
        comments = doc('#approval_status').find('.version-comments')

        eq_(comments.length, 2)


class TestUploadErrors(UploadTest):
    fixtures = ['base/apps', 'base/users',
                'base/addon_3615', 'base/platforms']
    validator_success = json.dumps({
        "errors": 0,
        "success": True,
        "warnings": 0,
        "notices": 0,
        "message_tree": {},
        "messages": [],
        "metadata": {},
    })

    def xpi(self):
        return open(os.path.join(os.path.dirname(files.__file__),
                                 'fixtures', 'files',
                                 'delicious_bookmarks-2.1.106-fx.xpi'),
                    'rb')

    @mock.patch.object(waffle, 'flag_is_active')
    @mock.patch('devhub.tasks.run_validator')
    def test_version_upload(self, run_validator, flag_is_active):
        run_validator.return_value = ''
        flag_is_active.return_value = True

        # Load the versions page:
        res = self.client.get(self.addon.get_dev_url('versions'))
        eq_(res.status_code, 200)
        doc = pq(res.content)

        # javascript: upload file:
        upload_url = doc('#upload-addon').attr('data-upload-url')
        with self.xpi() as f:
            res = self.client.post(upload_url, {'upload': f}, follow=True)
        data = json.loads(res.content)

        # Simulate the validation task finishing after a delay:
        run_validator.return_value = self.validator_success
        tasks.validator.delay(data['upload'])

        # javascript: poll for status:
        res = self.client.get(data['url'])
        data = json.loads(res.content)
        if data['validation'] and data['validation']['messages']:
            raise AssertionError('Unexpected validation errors: %s'
                                 % data['validation']['messages'])

    @mock.patch.object(waffle, 'flag_is_active')
    @mock.patch('devhub.tasks.run_validator')
    def test_dupe_xpi(self, run_validator, flag_is_active):
        run_validator.return_value = ''
        flag_is_active.return_value = True

        # Submit a new addon:
        self.client.post(reverse('devhub.submit.1'))  # set cookie
        res = self.client.get(reverse('devhub.submit.2'))
        eq_(res.status_code, 200)
        doc = pq(res.content)

        # javascript: upload file:
        upload_url = doc('#upload-addon').attr('data-upload-url')
        with self.xpi() as f:
            res = self.client.post(upload_url, {'upload': f}, follow=True)
        data = json.loads(res.content)

        # Simulate the validation task finishing after a delay:
        run_validator.return_value = self.validator_success
        tasks.validator.delay(data['upload'])

        # javascript: poll for results:
        res = self.client.get(data['url'])
        data = json.loads(res.content)
        eq_(list(m['message'] for m in data['validation']['messages']),
            [u'Duplicate UUID found.'])


class AddVersionTest(UploadTest):

    def post(self, desktop_platforms=[amo.PLATFORM_MAC], mobile_platforms=[],
                   expected_status=200):
        d = dict(upload=self.upload.pk,
                 desktop_platforms=[p.id for p in desktop_platforms],
                 mobile_platforms=[p.id for p in mobile_platforms])
        r = self.client.post(self.url, d)
        eq_(r.status_code, expected_status)
        return r

    def setUp(self):
        super(AddVersionTest, self).setUp()
        self.url = reverse('devhub.versions.add', args=[self.addon.slug])


class TestAddVersion(AddVersionTest):

    def test_unique_version_num(self):
        self.version.update(version='0.1')
        r = self.post(expected_status=400)
        assert_json_error(r, None, 'Version 0.1 already exists')

    def test_success(self):
        r = self.post()
        version = self.addon.versions.get(version='0.1')
        assert_json_field(r, 'url', reverse('devhub.versions.edit',
                                        args=[self.addon.slug, version.id]))

    def test_public(self):
        self.post()
        fle = File.objects.all().order_by("-created")[0]
        eq_(fle.status, amo.STATUS_PUBLIC)

    def test_not_public(self):
        self.addon.update(trusted=False)
        self.post()
        fle = File.objects.all().order_by("-created")[0]
        assert_not_equal(fle.status, amo.STATUS_PUBLIC)

    def test_multiple_platforms(self):
        r = self.post(desktop_platforms=[amo.PLATFORM_MAC,
                                         amo.PLATFORM_LINUX])
        eq_(r.status_code, 200)
        version = self.addon.versions.get(version='0.1')
        eq_(len(version.all_files), 2)


class TestAddBetaVersion(AddVersionTest):
    fixtures = ['base/apps', 'base/users', 'base/appversion',
                'base/addon_3615', 'base/platforms']

    def setUp(self):
        super(TestAddBetaVersion, self).setUp()

        self.do_upload()

    def do_upload(self):
        self.upload = self.get_upload('extension-0.2b1.xpi')

    def post_additional(self, version, platform=amo.PLATFORM_MAC):
        url = reverse('devhub.versions.add_file',
                      args=[self.addon.slug, version.id])
        return self.client.post(url, dict(upload=self.upload.pk,
                                          platform=platform.id))

    def test_add_multi_file_beta(self):
        r = self.post(desktop_platforms=[amo.PLATFORM_MAC])

        version = self.addon.versions.all().order_by('-id')[0]

        # Make sure that the first file is beta
        fle = File.objects.all().order_by('-id')[0]
        eq_(fle.status, amo.STATUS_BETA)

        self.do_upload()
        r = self.post_additional(version, platform=amo.PLATFORM_LINUX)
        eq_(r.status_code, 200)

        # Make sure that the additional files are beta
        fle = File.objects.all().order_by('-id')[0]
        eq_(fle.status, amo.STATUS_BETA)


class TestVersionXSS(UploadTest):

    def test_unique_version_num(self):
        self.version.update(
                version='<script>alert("Happy XSS-Xmas");</script>')
        r = self.client.get(reverse('devhub.addons'))
        eq_(r.status_code, 200)
        assert '<script>alert' not in r.content
        assert '&lt;script&gt;alert' in r.content


class UploadAddon(object):

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


class TestCreateAddon(BaseUploadTest, UploadAddon, amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/platforms']

    def setUp(self):
        super(TestCreateAddon, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        self.url = reverse('devhub.submit.2')
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.client.post(reverse('devhub.submit.1'))

    def assert_json_error(self, *args):
        UploadTest().assert_json_error(self, *args)

    def test_unique_name(self):
        addon_factory(name='xpi name')
        r = self.post(expect_errors=True)
        eq_(r.context['new_addon_form'].non_field_errors(),
            ['This name is already in use. Please choose another.'])

    def test_success(self):
        eq_(Addon.objects.count(), 0)
        r = self.post()
        addon = Addon.objects.get()
        self.assertRedirects(r, reverse('devhub.submit.3', args=[addon.slug]))
        log_items = ActivityLog.objects.for_addons(addon)
        assert log_items.filter(action=amo.LOG.CREATE_ADDON.id), (
            'New add-on creation never logged.')

    def test_missing_platforms(self):
        r = self.client.post(self.url, dict(upload=self.upload.pk))
        eq_(r.status_code, 200)
        eq_(r.context['new_addon_form'].errors.as_text(),
            '* __all__\n  * Need at least one platform.')
        doc = pq(r.content)
        eq_(doc('ul.errorlist').text(),
            'Need at least one platform.')

    def test_one_xpi_for_multiple_platforms(self):
        eq_(Addon.objects.count(), 0)
        r = self.post(desktop_platforms=[amo.PLATFORM_MAC,
                                         amo.PLATFORM_LINUX])
        addon = Addon.objects.get()
        self.assertRedirects(r, reverse('devhub.submit.3',
                                        args=[addon.slug]))
        eq_(sorted([f.filename for f in addon.current_version.all_files]),
            [u'xpi_name-0.1-linux.xpi', u'xpi_name-0.1-mac.xpi'])


class TestDeleteAddon(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.url = self.addon.get_dev_url('delete')
        self.client.login(username='admin@mozilla.com', password='password')

    def test_bad_password(self):
        r = self.client.post(self.url, dict(password='turd'))
        self.assertRedirects(r, self.addon.get_dev_url('versions'))
        eq_(r.context['title'],
            'Password was incorrect. Add-on was not deleted.')
        eq_(Addon.objects.count(), 1)

    def test_success(self):
        r = self.client.post(self.url, dict(password='password'))
        self.assertRedirects(r, reverse('devhub.addons'))
        eq_(r.context['title'], 'Add-on deleted.')
        eq_(Addon.objects.count(), 0)


class TestRequestReview(amo.tests.TestCase):
    fixtures = ['base/users', 'base/platforms']

    def setUp(self):
        self.addon = Addon.objects.create(type=1, name='xxx')
        self.version = Version.objects.create(addon=self.addon)
        self.file = File.objects.create(version=self.version,
                                        platform_id=amo.PLATFORM_ALL.id)
        self.redirect_url = self.addon.get_dev_url('versions')
        self.lite_url = reverse('devhub.request-review',
                                args=[self.addon.slug, amo.STATUS_LITE])
        self.public_url = reverse('devhub.request-review',
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


class TestRedirects(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.base = reverse('devhub.index')
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')

    def test_edit(self):
        url = self.base + 'addon/edit/3615'
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, reverse('devhub.addons.edit', args=['a3615']),
                             301)

        url = self.base + 'addon/edit/3615/'
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, reverse('devhub.addons.edit', args=['a3615']),
                             301)

    def test_status(self):
        url = self.base + 'addon/status/3615'
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, reverse('devhub.addons.versions',
                                        args=['a3615']), 301)

    def test_versions(self):
        url = self.base + 'versions/3615'
        r = self.client.get(url, follow=True)
        self.assertRedirects(r, reverse('devhub.addons.versions',
                                        args=['a3615']), 301)


class TestDocs(amo.tests.TestCase):

    def test_doc_urls(self):
        eq_('/en-US/developers/docs/', reverse('devhub.docs', args=[]))
        eq_('/en-US/developers/docs/te', reverse('devhub.docs', args=['te']))
        eq_('/en-US/developers/docs/te/st', reverse('devhub.docs',
                                                    args=['te', 'st']))

        urls = [(reverse('devhub.docs', args=["getting-started"]), 200),
                (reverse('devhub.docs', args=["how-to"]), 200),
                (reverse('devhub.docs', args=["how-to", "other-addons"]), 200),
                (reverse('devhub.docs', args=["fake-page"]), 302),
                (reverse('devhub.docs', args=["how-to", "fake-page"]), 200),
                (reverse('devhub.docs'), 302)]

        index = reverse('devhub.index')

        for url in urls:
            r = self.client.get(url[0])
            eq_(r.status_code, url[1])

            if url[1] == 302:  # Redirect to the index page
                self.assertRedirects(r, index)


class TestRemoveLocale(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'base/addon_3615']

    def setUp(self):
        self.addon = Addon.objects.get(id=3615)
        self.url = reverse('devhub.addons.remove-locale', args=['a3615'])
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

    def test_remove_version_locale(self):
        version = self.addon.versions.all()[0]
        version.releasenotes = {'fr': 'oui'}
        version.save()

        self.client.post(self.url, {'locale': 'fr'})
        res = self.client.get(reverse('devhub.versions.edit',
                                      args=[self.addon.slug, version.pk]))
        doc = pq(res.content)
        # There's 2 fields, one for en-us, one for init.
        eq_(len(doc('div.trans textarea')), 2)


class TestSearch(amo.tests.TestCase):

    def test_search_titles(self):
        r = self.client.get(reverse('devhub.search'), {'q': 'davor'})
        self.assertContains(r, '&#34;davor&#34;</h1>')
        self.assertContains(r, '<title>davor :: Search ::')

    def test_search_titles_default(self):
        r = self.client.get(reverse('devhub.search'))
        self.assertContains(r, '<title>Search ::')
        self.assertContains(r, '<h1>Search Results</h1>')
