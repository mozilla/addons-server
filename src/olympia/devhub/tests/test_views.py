
# -*- coding: utf-8 -*-
import json
import os
import socket
from datetime import datetime, timedelta
from decimal import Decimal

from django import http
from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.core.files import temp
from django.utils.translation import trim_whitespace

import mock
import waffle
from jingo.helpers import datetime as datetime_filter
from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo, paypal, files
from olympia.amo.tests import TestCase, version_factory
from olympia.addons.models import (
    Addon, AddonFeatureCompatibility, Charity)
from olympia.amo.helpers import url as url_reverse
from olympia.amo.tests import addon_factory, formset
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.api.models import APIKey, SYMMETRIC_JWT_TYPE
from olympia.applications.models import AppVersion
from olympia.devhub.forms import ContribForm
from olympia.devhub.models import ActivityLog, BlogPost
from olympia.devhub.tasks import validate
from olympia.files.models import File, FileUpload
from olympia.files.tests.test_models import UploadTest as BaseUploadTest
from olympia.reviews.models import Review
from olympia.translations.models import Translation
from olympia.users.models import UserProfile
from olympia.versions.models import ApplicationsVersions, Version


class HubTest(TestCase):
    fixtures = ['browse/nameless-addon', 'base/users']

    def setUp(self):
        super(HubTest, self).setUp()
        self.url = reverse('devhub.index')
        assert self.client.login(email='regular@mozilla.com')
        assert self.client.get(self.url).status_code == 200
        self.user_profile = UserProfile.objects.get(id=999)

    def clone_addon(self, num, addon_id=57132):
        ids = []
        for i in range(num):
            addon = Addon.objects.get(id=addon_id)
            data = dict(type=addon.type, status=addon.status,
                        name='cloned-addon-%s-%s' % (addon_id, i))
            new_addon = Addon.objects.create(**data)
            new_addon.addonuser_set.create(user=self.user_profile)
            ids.append(new_addon.id)
        return ids


class TestNav(HubTest):

    def test_navbar(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('#site-nav').length == 1

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        # My Add-ons menu should not be visible if user has no add-ons.
        assert doc('#navbar ul li.top a').eq(0).text() != 'My Add-ons'

    def test_my_addons(self):
        """Check that the correct items are listed for the My Add-ons menu."""
        # Assign this add-on to the current user profile.
        addon = Addon.objects.get(id=57132)
        addon.name = 'Test'
        addon.save()
        addon.addonuser_set.create(user=self.user_profile)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # Check the anchor for the 'My Add-ons' menu item.
        assert doc('#site-nav ul li.top a').eq(0).text() == 'My Add-ons'

        # Check the anchor for the single add-on.
        assert doc('#site-nav ul li.top li a').eq(0).attr('href') == (
            addon.get_dev_url())

        # Create 6 add-ons.
        self.clone_addon(6)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # There should be 8 items in this menu.
        assert doc('#site-nav ul li.top').eq(0).find('ul li').length == 8

        # This should be the 8th anchor, after the 7 addons.
        assert doc('#site-nav ul li.top').eq(0).find('li a').eq(7).text() == (
            'Submit a New Add-on')

        self.clone_addon(1)

        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('#site-nav ul li.top').eq(0).find('li a').eq(7).text() == (
            'more add-ons...')

    def test_unlisted_addons_are_displayed(self):
        """Check that unlisted addons are displayed in the nav."""
        # Assign this add-on to the current user profile.
        addon = Addon.objects.get(id=57132)
        addon.name = 'Test'
        addon.is_listed = False
        addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        addon.save()
        addon.addonuser_set.create(user=self.user_profile)

        r = self.client.get(self.url)
        doc = pq(r.content)

        # Check the anchor for the unlisted add-on.
        assert doc('#site-nav ul li.top li a').eq(0).attr('href') == (
            addon.get_dev_url())


class TestDashboard(HubTest):

    def setUp(self):
        super(TestDashboard, self).setUp()
        self.url = reverse('devhub.addons')
        self.themes_url = reverse('devhub.themes')
        assert self.client.get(self.url).status_code == 200
        self.addon = Addon.objects.get(pk=57132)
        self.addon.name = 'some addon'
        self.addon.save()
        self.addon.addonuser_set.create(user=self.user_profile)

    def test_addons_layout(self):
        doc = pq(self.client.get(self.url).content)
        assert doc('title').text() == (
            'Manage My Submissions :: Developer Hub :: Add-ons for Firefox')
        assert doc('.links-footer').length == 1
        assert doc('#copyright').length == 1
        assert doc('#footer-links .mobile-link').length == 0

    def get_action_links(self, addon_id):
        r = self.client.get(self.url)
        doc = pq(r.content)
        selector = '.item[data-addonid="%s"] .item-actions li > a' % addon_id
        links = [a.text.strip() for a in doc(selector)]
        return links

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('.item item').length == 0

    def test_addon_pagination(self):
        """Check that the correct info. is displayed for each add-on:
        namely, that add-ons are paginated at 10 items per page, and that
        when there is more than one page, the 'Sort by' header and pagination
        footer appear.

        """
        # Create 9 add-ons, there's already one existing from the setUp.
        self.clone_addon(9)
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert len(doc('.item .item-info')) == 10
        assert doc('nav.paginator').length == 0

        # Create 5 add-ons.
        self.clone_addon(5)
        r = self.client.get(self.url, dict(page=2))
        doc = pq(r.content)
        assert len(doc('.item .item-info')) == 5
        assert doc('nav.paginator').length == 1

    def test_themes(self):
        """Check themes show on dashboard."""
        # Create 2 themes.
        for x in range(2):
            addon = addon_factory(type=amo.ADDON_PERSONA)
            addon.addonuser_set.create(user=self.user_profile)
        r = self.client.get(self.themes_url)
        doc = pq(r.content)
        assert len(doc('.item .item-info')) == 2

    def test_show_hide_statistics(self):
        # when Active and Public show statistics
        self.addon.update(disabled_by_user=False, status=amo.STATUS_PUBLIC)
        links = self.get_action_links(self.addon.pk)
        assert 'Statistics' in links, ('Unexpected: %r' % links)

        # when Active and Incomplete hide statistics
        self.addon.update(disabled_by_user=False, status=amo.STATUS_NULL)
        links = self.get_action_links(self.addon.pk)
        assert 'Statistics' not in links, ('Unexpected: %r' % links)

    def test_public_addon(self):
        assert self.addon.status == amo.STATUS_PUBLIC
        doc = pq(self.client.get(self.url).content)
        item = doc('.item[data-addonid="%s"]' % self.addon.id)
        assert item.find('h3 a').attr('href') == self.addon.get_dev_url()
        assert item.find('p.downloads'), 'Expected weekly downloads'
        assert item.find('p.users'), 'Expected ADU'
        assert item.find('.item-details'), 'Expected item details'
        assert not item.find('p.incomplete'), (
            'Unexpected message about incomplete add-on')
        # Addon is not set to be compatible with Firefox, e10s compatibility is
        # not shown.
        assert not item.find('.e10s-compatibility')

    def test_e10s_compatibility(self):
        self.addon = addon_factory(name=u'My Addœn')
        self.addon.addonuser_set.create(user=self.user_profile)

        doc = pq(self.client.get(self.url).content)
        item = doc('.item[data-addonid="%s"]' % self.addon.id)
        e10s_flag = item.find('.e10s-compatibility.e10s-unknown b')
        assert e10s_flag
        assert e10s_flag.text() == 'Unknown'

        AddonFeatureCompatibility.objects.create(
            addon=self.addon, e10s=amo.E10S_COMPATIBLE)
        doc = pq(self.client.get(self.url).content)
        item = doc('.item[data-addonid="%s"]' % self.addon.id)
        assert not item.find('.e10s-compatibility.e10s-unknown')
        e10s_flag = item.find('.e10s-compatibility.e10s-compatible b')
        assert e10s_flag
        assert e10s_flag.text() == 'Compatible'

    def test_dev_news(self):
        for i in xrange(7):
            bp = BlogPost(title='hi %s' % i,
                          date_posted=datetime.now() - timedelta(days=i))
            bp.save()
        r = self.client.get(self.url)
        doc = pq(r.content)

        assert doc('.blog-posts').length == 1
        assert doc('.blog-posts li').length == 5
        assert doc('.blog-posts li a').eq(0).text() == "hi 0"
        assert doc('.blog-posts li a').eq(4).text() == "hi 4"

    def test_sort_created_filter(self):
        response = self.client.get(self.url + '?sort=created')
        doc = pq(response.content)
        assert doc('.item-details').length == 1
        d = doc('.item-details .date-created')
        assert d.length == 1
        assert d.remove('strong').text() == (
            datetime_filter(self.addon.created, '%b %e, %Y'))

    def test_sort_updated_filter(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.item-details').length == 1
        d = doc('.item-details .date-updated')
        assert d.length == 1
        assert d.remove('strong').text() == (
            trim_whitespace(
                datetime_filter(self.addon.last_updated, '%b %e, %Y')))

    def test_no_sort_updated_filter_for_themes(self):
        # Create a theme.
        addon = addon_factory(type=amo.ADDON_PERSONA)
        addon.addonuser_set.create(user=self.user_profile)

        # There's no "updated" sort filter, so order by the default: "Name".
        response = self.client.get(self.themes_url + '?sort=updated')
        doc = pq(response.content)
        assert doc('#sorter li.selected').text() == 'Name'
        sorts = doc('#sorter li a.opt')
        assert not any('?sort=updated' in a.attrib['href'] for a in sorts)

        # No "updated" in details.
        assert doc('.item-details .date-updated') == []
        # There's no "last updated" for themes, so always display "created".
        d = doc('.item-details .date-created')
        assert d.remove('strong').text() == (
            trim_whitespace(datetime_filter(addon.created)))


class TestUpdateCompatibility(TestCase):
    fixtures = ['base/users', 'base/addon_4594_a9', 'base/addon_3615']

    def setUp(self):
        super(TestUpdateCompatibility, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.url = reverse('devhub.addons')

        self._versions = amo.FIREFOX.latest_version, amo.MOBILE.latest_version
        amo.FIREFOX.latest_version = amo.MOBILE.latest_version = '3.6.15'

    def tearDown(self):
        amo.FIREFOX.latest_version, amo.MOBILE.latest_version = self._versions
        super(TestUpdateCompatibility, self).tearDown()

    def test_no_compat(self):
        self.client.logout()
        assert self.client.login(email='admin@mozilla.com')
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert not doc('.item[data-addonid="4594"] li.compat')
        a = Addon.objects.get(pk=4594)
        r = self.client.get(reverse('devhub.ajax.compat.update',
                                    args=[a.slug, a.current_version.id]))
        assert r.status_code == 404
        r = self.client.get(reverse('devhub.ajax.compat.status',
                                    args=[a.slug]))
        assert r.status_code == 404

    def test_compat(self):
        a = Addon.objects.get(pk=3615)

        r = self.client.get(self.url)
        doc = pq(r.content)
        cu = doc('.item[data-addonid="3615"] .tooltip.compat-update')
        assert cu

        update_url = reverse('devhub.ajax.compat.update',
                             args=[a.slug, a.current_version.id])
        assert cu.attr('data-updateurl') == update_url

        status_url = reverse('devhub.ajax.compat.status', args=[a.slug])
        selector = '.item[data-addonid="3615"] li.compat'
        assert doc(selector).attr('data-src') == status_url

        assert doc('.item[data-addonid="3615"] .compat-update-modal')

    def test_incompat_firefox(self):
        versions = ApplicationsVersions.objects.all()[0]
        versions.max = AppVersion.objects.get(version='2.0')
        versions.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('.item[data-addonid="3615"] .tooltip.compat-error')

    def test_incompat_mobile(self):
        appver = AppVersion.objects.get(version='2.0')
        appver.update(application=amo.MOBILE.id)
        av = ApplicationsVersions.objects.all()[0]
        av.application = amo.MOBILE.id
        av.max = appver
        av.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('.item[data-addonid="3615"] .tooltip.compat-error')


class TestDevRequired(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestDevRequired, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.get_url = self.addon.get_dev_url('payments')
        self.post_url = self.addon.get_dev_url('payments.disable')
        assert self.client.login(email='del@icio.us')
        self.au = self.addon.addonuser_set.get(user__email='del@icio.us')
        assert self.au.role == amo.AUTHOR_ROLE_OWNER

    def test_anon(self):
        self.client.logout()
        self.assertLoginRedirects(self.client.get(self.get_url), self.get_url)

    def test_dev_get(self):
        assert self.client.get(self.get_url).status_code == 200

    def test_dev_post(self):
        self.assert3xx(self.client.post(self.post_url), self.get_url)

    def test_viewer_get(self):
        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        assert self.client.get(self.get_url).status_code == 200

    def test_viewer_post(self):
        self.au.role = amo.AUTHOR_ROLE_VIEWER
        self.au.save()
        assert self.client.post(self.get_url).status_code == 403

    def test_disabled_post_dev(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.post(self.get_url).status_code == 403

    def test_disabled_post_admin(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        assert self.client.login(email='admin@mozilla.com')
        self.assert3xx(self.client.post(self.post_url), self.get_url)


class TestVersionStats(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestVersionStats, self).setUp()
        assert self.client.login(email='admin@mozilla.com')

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


class TestEditPayments(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestEditPayments, self).setUp()
        self.addon = self.get_addon()
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        self.foundation = Charity.objects.create(
            id=amo.FOUNDATION_ORG, name='moz', url='$$.moz', paypal='moz.pal')
        self.url = self.addon.get_dev_url('payments')
        assert self.client.login(email='del@icio.us')
        self.paypal_mock = mock.Mock()
        self.paypal_mock.return_value = (True, None)
        paypal.check_paypal_id = self.paypal_mock

    def get_addon(self):
        return Addon.objects.no_cache().get(id=3615)

    def post(self, *args, **kw):
        d = dict(*args, **kw)
        assert self.client.post(self.url, d).status_code == 302

    def check(self, **kw):
        addon = self.get_addon()
        for k, v in kw.items():
            assert getattr(addon, k) == v
        assert addon.wants_contributions
        assert addon.takes_contributions

    def test_logging(self):
        count = ActivityLog.objects.all().count()
        self.post(recipient='dev', suggested_amount=2, paypal_id='greed@dev',
                  annoying=amo.CONTRIB_AFTER)
        assert ActivityLog.objects.all().count() == count + 1

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
        assert int(doc('#id_paypal_id').attr('size')) == 50

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
        assert self.get_addon().suggested_amount is None

    def test_switch_charity_to_dev(self):
        self.test_success_charity()
        self.test_success_dev()
        assert self.get_addon().charity is None
        assert self.get_addon().charity_id is None

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
        assert moz.name == 'moz'
        assert moz.url == '$$.moz'
        assert moz.paypal == 'moz.pal'

    def test_contrib_form_initial(self):
        assert ContribForm.initial(self.addon)['recipient'] == 'dev'
        self.addon.charity = self.foundation
        assert ContribForm.initial(self.addon)['recipient'] == 'moz'
        self.addon.charity_id = amo.FOUNDATION_ORG + 1
        assert ContribForm.initial(self.addon)['recipient'] == 'org'

        assert ContribForm.initial(self.addon)['annoying'] == (
            amo.CONTRIB_PASSIVE)
        self.addon.annoying = amo.CONTRIB_AFTER
        assert ContribForm.initial(self.addon)['annoying'] == (
            amo.CONTRIB_AFTER)

    def test_enable_thankyou(self):
        d = dict(enable_thankyou='on', thankyou_note='woo',
                 annoying=1, recipient='moz')
        r = self.client.post(self.url, d)
        assert r.status_code == 302
        addon = self.get_addon()
        assert addon.enable_thankyou
        assert unicode(addon.thankyou_note) == 'woo'

    def test_enable_thankyou_unchecked_with_text(self):
        d = dict(enable_thankyou='', thankyou_note='woo',
                 annoying=1, recipient='moz')
        r = self.client.post(self.url, d)
        assert r.status_code == 302
        addon = self.get_addon()
        assert not addon.enable_thankyou
        assert addon.thankyou_note is None

    def test_contribution_link(self):
        self.test_success_foundation()
        r = self.client.get(self.url)
        doc = pq(r.content)

        span = doc('#status-bar').find('span')
        assert span.length == 1
        assert span.text().startswith('Your contribution page: ')

        a = span.find('a')
        assert a.length == 1
        assert a.attr('href') == reverse(
            'addons.about', args=[self.get_addon().slug])
        assert a.text() == url_reverse(
            'addons.about', self.get_addon().slug, host=settings.SITE_URL)

    def test_enable_thankyou_no_text(self):
        d = dict(enable_thankyou='on', thankyou_note='',
                 annoying=1, recipient='moz')
        r = self.client.post(self.url, d)
        assert r.status_code == 302
        addon = self.get_addon()
        assert not addon.enable_thankyou
        assert addon.thankyou_note is None

    def test_no_future(self):
        self.get_addon().update(the_future=None)
        res = self.client.get(self.url)
        err = pq(res.content)('p.error').text()
        assert 'completed developer profile' in err

    def test_addon_public(self):
        self.get_addon().update(status=amo.STATUS_PUBLIC)
        res = self.client.get(self.url)
        doc = pq(res.content)
        assert doc('#do-setup').text() == 'Set up Contributions'

    def test_voluntary_contributions_addons(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('.intro').length == 1
        assert doc('.intro.full-intro').length == 0

    def test_no_voluntary_contributions_for_unlisted_addons(self):
        self.addon.current_version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.addon.update(is_listed=False)
        r = self.client.get(self.url)
        doc = pq(r.content)
        assert doc('.intro').length == 1
        assert doc('.intro.full-intro').length == 0
        assert not doc('#do-setup')  # No way to setup the payment.
        assert doc('.intro .error').text().startswith(
            'Contributions are only available for add-ons with listed')


class TestDisablePayments(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestDisablePayments, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        self.addon.update(wants_contributions=True, paypal_id='woohoo')
        self.pay_url = self.addon.get_dev_url('payments')
        self.disable_url = self.addon.get_dev_url('payments.disable')
        assert self.client.login(email='del@icio.us')

    def test_statusbar_visible(self):
        r = self.client.get(self.pay_url)
        self.assertContains(r, '<div id="status-bar">')

        self.addon.update(wants_contributions=False)
        r = self.client.get(self.pay_url)
        self.assertNotContains(r, '<div id="status-bar">')

    def test_disable(self):
        r = self.client.post(self.disable_url)
        assert r.status_code == 302
        assert(r['Location'].endswith(self.pay_url))
        assert not Addon.objects.no_cache().get(id=3615).wants_contributions


class TestPaymentsProfile(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestPaymentsProfile, self).setUp()
        self.addon = a = self.get_addon()
        self.url = self.addon.get_dev_url('payments')
        # Make sure all the payment/profile data is clear.
        assert not (a.wants_contributions or a.paypal_id or a.the_reason or
                    a.the_future or a.takes_contributions)
        assert self.client.login(email='del@icio.us')
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
        assert r.status_code == 302

        # The profile form is gone, we're accepting contributions.
        doc = pq(self.client.get(self.url).content)
        assert not doc('.intro')
        assert not doc('#setup.hidden')
        assert doc('#status-bar')
        assert not doc('#trans-the_reason')
        assert not doc('#trans-the_future')

        addon = self.get_addon()
        assert unicode(addon.the_reason) == 'xxx'
        assert unicode(addon.the_future) == 'yyy'
        assert addon.wants_contributions

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
        assert r.status_code == 200
        self.assertFormError(r, 'profile_form', 'the_reason',
                             'This field is required.')
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')
        check_page(r)
        assert not self.get_addon().wants_contributions

        d = dict(recipient='dev', suggested_amount=2, paypal_id='xx@yy',
                 annoying=amo.CONTRIB_ROADBLOCK, the_reason='xxx')
        r = self.client.post(self.url, d)
        assert r.status_code == 200
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')
        check_page(r)
        assert not self.get_addon().wants_contributions


class TestDelete(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestDelete, self).setUp()
        self.get_addon = lambda: Addon.objects.filter(id=3615)
        assert self.client.login(email='del@icio.us')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.get_url = lambda: self.get_addon()[0].get_dev_url('delete')

    def make_theme(self):
        theme = addon_factory(
            name='xpi name', type=amo.ADDON_PERSONA, slug='theme-slug')
        theme.authors.through.objects.create(addon=theme, user=self.user)
        return theme

    def test_post_not(self):
        r = self.client.post(self.get_url(), follow=True)
        assert pq(r.content)('.notification-box').text() == (
            'URL name was incorrect. Add-on was not deleted.')
        assert self.get_addon().exists()

    def test_post(self):
        self.get_addon().get().update(slug='addon-slug')
        r = self.client.post(self.get_url(), {'slug': 'addon-slug'},
                             follow=True)
        assert pq(r.content)('.notification-box').text() == 'Add-on deleted.'
        assert not self.get_addon().exists()

    def test_post_wrong_slug(self):
        self.get_addon().get().update(slug='addon-slug')
        r = self.client.post(self.get_url(), {'slug': 'theme-slug'},
                             follow=True)
        assert pq(r.content)('.notification-box').text() == (
            'URL name was incorrect. Add-on was not deleted.')
        assert self.get_addon().exists()

    def test_post_theme(self):
        theme = self.make_theme()
        r = self.client.post(
            theme.get_dev_url('delete'), {'slug': 'theme-slug'}, follow=True)
        assert pq(r.content)('.notification-box').text() == 'Theme deleted.'
        assert not Addon.objects.filter(id=theme.id).exists()

    def test_post_theme_wrong_slug(self):
        theme = self.make_theme()
        r = self.client.post(
            theme.get_dev_url('delete'), {'slug': 'addon-slug'}, follow=True)
        assert pq(r.content)('.notification-box').text() == (
            'URL name was incorrect. Theme was not deleted.')
        assert Addon.objects.filter(id=theme.id).exists()


class TestHome(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestHome, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.url = reverse('devhub.index')
        self.addon = Addon.objects.get(pk=3615)

    def get_pq(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        return pq(r.content)

    def test_addons(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        self.assertTemplateUsed(r, 'devhub/index.html')

    def test_editor_promo(self):
        assert self.get_pq()('#devhub-sidebar #editor-promo').length == 1

    def test_no_editor_promo(self):
        Addon.objects.all().delete()
        # Regular users (non-devs) should not see this promo.
        assert self.get_pq()('#devhub-sidebar #editor-promo').length == 0

    @override_switch('step-version-upload', active=False)
    def test_my_addons_inline_version_upload(self):
        statuses = [(amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW),
                    (amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW)]

        for addon_status, file_status in statuses:
            latest_version = self.addon.find_latest_version()
            file = latest_version.files.all()[0]
            file.update(status=file_status)

            self.addon.update(status=addon_status)

            doc = self.get_pq()
            addon_item = doc('#my-addons .addon-item')
            assert addon_item.length == 1
            assert addon_item.find('.addon-name').attr('href') == (
                self.addon.get_dev_url('edit'))
            if self.addon.is_listed and self.addon.current_version:
                # We don't display a link to the inexistent public page for
                # unlisted addons.
                assert addon_item.find('p').eq(2).find('a').attr('href') == (
                    self.addon.current_version.get_url_path())
                assert 'Queue Position: 1 of 1' == (
                    addon_item.find('p').eq(3).text())

            assert addon_item.find(
                '.upload-new-version a').attr('href') == (
                self.addon.get_dev_url('versions') + '#version-upload')

            doc = self.get_pq()
            addon_item = doc('#my-addons .addon-item')
            status_str = 'Status: ' + unicode(
                self.addon.STATUS_CHOICES[self.addon.status])
            assert status_str == addon_item.find('p').eq(1).text()

        Addon.with_unlisted.all().delete()
        assert self.get_pq()('#my-addons').length == 0

    @override_switch('step-version-upload', active=False)
    def test_my_addons_disabled_inline_version_upload(self):
        statuses = [(amo.STATUS_DISABLED, amo.STATUS_DISABLED)]

        for addon_status, file_status in statuses:
            latest_version = self.addon.find_latest_version()
            file = latest_version.files.all()[0]
            file.update(status=file_status)

            self.addon.update(status=addon_status)

            doc = self.get_pq()
            addon_item = doc('#my-addons .addon-item')
            assert addon_item.length == 1
            assert addon_item.find('.addon-name').attr('href') == (
                self.addon.get_dev_url('edit'))
            if self.addon.is_listed and self.addon.current_version:
                # We don't display a link to the inexistent public page for
                # unlisted addons.
                assert addon_item.find('p').eq(3).find('a').attr('href') == (
                    self.addon.current_version.get_url_path())
            assert not addon_item.find('.upload-new-version a')

            doc = self.get_pq()
            addon_item = doc('#my-addons .addon-item')
            status_str = 'Status: ' + unicode(
                self.addon.STATUS_CHOICES[self.addon.status])
            assert status_str == addon_item.find('p').eq(1).text()

        Addon.with_unlisted.all().delete()
        assert self.get_pq()('#my-addons').length == 0

    def test_my_unlisted_addons_inline_version_upload(self):
        self.addon.update(is_listed=False)
        # Run the test again but with an unlisted addon.
        self.test_my_addons_inline_version_upload()

    @override_switch('step-version-upload', active=True)
    def test_my_addons(self):
        statuses = [(amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW),
                    (amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW)]

        for addon_status, file_status in statuses:
            latest_version = self.addon.find_latest_version()
            file = latest_version.files.all()[0]
            file.update(status=file_status)

            self.addon.update(status=addon_status)

            doc = self.get_pq()
            addon_item = doc('#my-addons .addon-item')
            assert addon_item.length == 1
            assert addon_item.find('.addon-name').attr('href') == (
                self.addon.get_dev_url('edit'))
            assert addon_item.find('p').eq(2).find('a').attr('href') == (
                self.addon.current_version.get_url_path())
            assert 'Queue Position: 1 of 1' == (
                addon_item.find('p').eq(3).text())

            assert addon_item.find(
                '.upload-new-version a').attr('href') == (
                reverse('devhub.submit.version', args=[self.addon.slug]))

            doc = self.get_pq()
            addon_item = doc('#my-addons .addon-item')
            status_str = 'Status: ' + unicode(
                self.addon.STATUS_CHOICES[self.addon.status])
            assert status_str == addon_item.find('p').eq(1).text()

        Addon.with_unlisted.all().delete()
        assert self.get_pq()('#my-addons').length == 0

    @override_switch('step-version-upload', active=True)
    def test_my_addons_disabled(self):
        latest_version = self.addon.find_latest_version()
        file = latest_version.files.all()[0]
        file.update(status=amo.STATUS_DISABLED)
        self.addon.update(status=amo.STATUS_DISABLED)

        doc = self.get_pq()
        addon_item = doc('#my-addons .addon-item')
        assert addon_item.length == 1
        assert addon_item.find('.addon-name').attr('href') == (
            self.addon.get_dev_url('edit'))
        assert not addon_item.find('p').eq(3).find('a').attr('href')
        assert not addon_item.find('.upload-new-version a')

        doc = self.get_pq()
        addon_item = doc('#my-addons .addon-item')
        status_str = 'Status: ' + unicode(
            self.addon.STATUS_CHOICES[self.addon.status])
        assert status_str == addon_item.find('p').eq(1).text()

        Addon.with_unlisted.all().delete()
        assert self.get_pq()('#my-addons').length == 0

    @override_switch('step-version-upload', active=True)
    def test_my_unlisted_addons(self):
        self.addon.update(is_listed=False)
        for v in self.addon.versions.all():
            v.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert self.addon.status == amo.STATUS_NULL

        doc = self.get_pq()
        addon_item = doc('#my-addons .addon-item')
        assert addon_item.length == 1
        assert addon_item.find('.addon-name').attr('href') == (
            self.addon.get_dev_url('edit'))

        assert addon_item.find(
            '.upload-new-version a').attr('href') == (
            reverse('devhub.submit.version', args=[self.addon.slug]))

        doc = self.get_pq()
        addon_item = doc('#my-addons .addon-item')
        status_str = 'Status: ' + unicode(
            self.addon.STATUS_CHOICES[self.addon.status])
        assert status_str == addon_item.find('p').eq(1).text()

        Addon.with_unlisted.all().delete()
        assert self.get_pq()('#my-addons').length == 0

    def test_incomplete_no_new_version(self):
        def no_link():
            doc = self.get_pq()
            addon_item = doc('#my-addons .addon-item')
            assert addon_item.length == 1
            assert addon_item.find('.upload-new-version').length == 0

        self.addon.update(status=amo.STATUS_NULL)
        self.addon.categories.all().delete()  # Make the add-on incomplete.
        no_link()

        self.addon.update(status=amo.STATUS_DISABLED)
        no_link()

        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        no_link()


class TestActivityFeed(TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        super(TestActivityFeed, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.versions.first()

    def test_feed_for_all(self):
        r = self.client.get(reverse('devhub.feed_all'))
        assert r.status_code == 200
        doc = pq(r.content)
        assert doc('header h2').text() == 'Recent Activity for My Add-ons'
        assert doc('#breadcrumbs li:eq(2)').text() == 'Recent Activity'

    def test_feed_for_addon(self):
        r = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        assert r.status_code == 200
        doc = pq(r.content)
        assert doc('header h2').text() == (
            'Recent Activity for %s' % self.addon.name)
        assert doc('#breadcrumbs li:eq(3)').text() == self.addon.slug

    def test_feed_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        r = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        assert r.status_code == 200

    def test_feed_disabled_anon(self):
        self.client.logout()
        r = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        assert r.status_code == 302

    def add_log(self, action=amo.LOG.ADD_REVIEW):
        amo.set_user(UserProfile.objects.get(email='del@icio.us'))
        amo.log(action, self.addon, self.version)

    def add_hidden_log(self, action=amo.LOG.COMMENT_VERSION):
        self.add_log(action=action)

    def test_feed_hidden(self):
        self.add_hidden_log()
        self.add_hidden_log(amo.LOG.OBJECT_ADDED)
        res = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        doc = pq(res.content)
        assert len(doc('#recent-activity li.item')) == 0

    def test_addons_hidden(self):
        self.add_hidden_log()
        self.add_hidden_log(amo.LOG.OBJECT_ADDED)
        res = self.client.get(reverse('devhub.addons'))
        doc = pq(res.content)
        assert len(doc('.recent-activity li.item')) == 0

    def test_unlisted_addons_dashboard(self):
        """Unlisted addons are displayed in the feed on the dashboard page."""
        self.addon.update(is_listed=False)
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.add_log()
        res = self.client.get(reverse('devhub.addons'))
        doc = pq(res.content)
        assert len(doc('.recent-activity li.item')) == 1

    def test_unlisted_addons_feed_sidebar(self):
        """Unlisted addons are displayed in the left side in the feed page."""
        self.addon.update(is_listed=False)
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.add_log()
        res = self.client.get(reverse('devhub.feed_all'))
        doc = pq(res.content)
        # First li is "All My Add-ons".
        assert len(doc('#refine-addon li')) == 2

    def test_unlisted_addons_feed(self):
        """Unlisted addons are displayed in the feed page."""
        self.addon.update(is_listed=False)
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.add_log()
        res = self.client.get(reverse('devhub.feed_all'))
        doc = pq(res.content)
        assert len(doc('#recent-activity .item')) == 1

    def test_unlisted_addons_feed_filter(self):
        """Feed page can be filtered on unlisted addon."""
        self.addon.update(is_listed=False)
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.add_log()
        res = self.client.get(reverse('devhub.feed', args=[self.addon.slug]))
        doc = pq(res.content)
        assert len(doc('#recent-activity .item')) == 1


class TestProfileBase(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestProfileBase, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.url = self.addon.get_dev_url('profile')
        assert self.client.login(email='del@icio.us')

    def get_addon(self):
        return Addon.objects.no_cache().get(id=self.addon.id)

    def enable_addon_contributions(self):
        self.addon.wants_contributions = True
        self.addon.paypal_id = 'somebody'
        self.addon.save()

    def post(self, *args, **kw):
        d = dict(*args, **kw)
        assert self.client.post(self.url, d).status_code == 302

    def check(self, **kw):
        addon = self.get_addon()
        for k, v in kw.items():
            if k in ('the_reason', 'the_future'):
                assert getattr(getattr(addon, k), 'localized_string') == (
                    unicode(v))
            else:
                assert getattr(addon, k) == v


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
        assert doc('#status-bar button').text() == 'Remove Profile'

    def test_status_bar_with_contrib(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.wants_contributions = True
        self.addon.paypal_id = 'xxx'
        self.addon.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('#status-bar')
        assert doc('#status-bar button').text() == 'Remove Both'

    def test_remove_profile(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.save()
        self.client.post(self.remove_url)
        addon = self.get_addon()
        assert addon.the_reason is None
        assert addon.the_future is None
        assert not addon.takes_contributions
        assert not addon.wants_contributions

    def test_remove_profile_without_content(self):
        # See bug 624852
        self.addon.the_reason = self.addon.the_future = None
        self.addon.save()
        self.client.post(self.remove_url)
        addon = self.get_addon()
        assert addon.the_reason is None
        assert addon.the_future is None

    def test_remove_both(self):
        self.addon.the_reason = self.addon.the_future = '...'
        self.addon.wants_contributions = True
        self.addon.paypal_id = 'xxx'
        self.addon.save()
        self.client.post(self.remove_url)
        addon = self.get_addon()
        assert addon.the_reason is None
        assert addon.the_future is None
        assert not addon.takes_contributions
        assert not addon.wants_contributions


class TestProfile(TestProfileBase):

    def test_without_contributions_labels(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        doc = pq(r.content)
        assert doc('label[for=the_reason] .optional').length == 1
        assert doc('label[for=the_future] .optional').length == 1

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
        assert o.count() == 0
        self.client.post(self.url, d)
        assert o.filter(action=amo.LOG.EDIT_PROPERTIES.id).count() == 1

    def test_with_contributions_fields_required(self):
        self.enable_addon_contributions()

        d = dict(the_reason='', the_future='')
        r = self.client.post(self.url, d)
        assert r.status_code == 200
        self.assertFormError(r, 'profile_form', 'the_reason',
                             'This field is required.')
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')

        d = dict(the_reason='to be cool', the_future='')
        r = self.client.post(self.url, d)
        assert r.status_code == 200
        self.assertFormError(r, 'profile_form', 'the_future',
                             'This field is required.')

        d = dict(the_reason='', the_future='hot stuff')
        r = self.client.post(self.url, d)
        assert r.status_code == 200
        self.assertFormError(r, 'profile_form', 'the_reason',
                             'This field is required.')

        self.post(the_reason='to be hot', the_future='cold stuff')
        self.check(the_reason='to be hot', the_future='cold stuff')


class TestAPIAgreement(TestCase):
    fixtures = ['base/addon_3615', 'base/addon_5579', 'base/users']

    def setUp(self):
        super(TestAPIAgreement, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.user = UserProfile.objects.get(email='del@icio.us')

    def test_agreement_first(self):
        render_agreement_path = 'olympia.devhub.views.render_agreement'
        with mock.patch(render_agreement_path) as mock_submit:
            mock_submit.return_value = http.HttpResponse("Okay")
            self.client.get(reverse('devhub.api_key_agreement'))
        assert mock_submit.called

    def test_agreement_second(self):
        self.user.update(read_dev_agreement=None)

        response = self.client.post(reverse('devhub.api_key_agreement'),
                                    follow=True)

        self.assert3xx(response, reverse('devhub.api_key'))


class TestAPIKeyPage(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestAPIKeyPage, self).setUp()
        self.url = reverse('devhub.api_key')
        assert self.client.login(email='del@icio.us')
        self.user = UserProfile.objects.get(email='del@icio.us')

    def test_key_redirect(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.api_key'))
        self.assert3xx(response, reverse('devhub.api_key_agreement'))

    def test_view_without_credentials(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        submit = doc('#generate-key')
        assert submit.text() == 'Generate new credentials'
        inputs = doc('.api-input input')
        assert len(inputs) == 0, 'Inputs should be hidden before keys exist'

    def test_view_with_credentials(self):
        APIKey.objects.create(user=self.user,
                              type=SYMMETRIC_JWT_TYPE,
                              key='some-jwt-key',
                              secret='some-jwt-secret')
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
        submit = doc('#generate-key')
        assert submit.text() == 'Revoke and regenerate credentials'
        assert doc('#revoke-key').text() == 'Revoke'
        key_input = doc('.key-input input').val()
        assert key_input == 'some-jwt-key'

    def test_create_new_credentials(self):
        patch = mock.patch('olympia.devhub.views.APIKey.new_jwt_credentials')
        with patch as mock_creator:
            response = self.client.post(self.url, data={'action': 'generate'})
        mock_creator.assert_called_with(self.user)

        email = mail.outbox[0]
        assert len(mail.outbox) == 1
        assert email.to == [self.user.email]
        assert reverse('devhub.api_key') in email.body

        self.assert3xx(response, self.url)

    def test_delete_and_recreate_credentials(self):
        old_key = APIKey.objects.create(user=self.user,
                                        type=SYMMETRIC_JWT_TYPE,
                                        key='some-jwt-key',
                                        secret='some-jwt-secret')
        response = self.client.post(self.url, data={'action': 'generate'})
        self.assert3xx(response, self.url)

        old_key = APIKey.objects.get(pk=old_key.pk)
        assert not old_key.is_active

        new_key = APIKey.get_jwt_key(user=self.user)
        assert new_key.key != old_key.key
        assert new_key.secret != old_key.secret

    def test_delete_credentials(self):
        old_key = APIKey.objects.create(user=self.user,
                                        type=SYMMETRIC_JWT_TYPE,
                                        key='some-jwt-key',
                                        secret='some-jwt-secret')
        response = self.client.post(self.url, data={'action': 'revoke'})
        self.assert3xx(response, self.url)

        old_key = APIKey.objects.get(pk=old_key.pk)
        assert not old_key.is_active

        assert len(mail.outbox) == 1
        assert 'revoked' in mail.outbox[0].body


class TestUpload(BaseUploadTest):
    fixtures = ['base/users']

    def setUp(self):
        super(TestUpload, self).setUp()
        assert self.client.login(email='regular@mozilla.com')
        self.url = reverse('devhub.upload')
        self.image_path = get_image_path('animated.png')

    def post(self):
        # Has to be a binary, non xpi file.
        data = open(self.image_path, 'rb')
        return self.client.post(self.url, {'upload': data})

    def test_login_required(self):
        self.client.logout()
        r = self.post()
        assert r.status_code == 302

    def test_create_fileupload(self):
        self.post()

        upload = FileUpload.objects.filter().order_by('-created').first()
        assert 'animated.png' in upload.name
        data = open(self.image_path, 'rb').read()
        assert storage.open(upload.path).read() == data

    def test_fileupload_user(self):
        self.client.login(email='regular@mozilla.com')
        self.post()
        user = UserProfile.objects.get(email='regular@mozilla.com')
        assert FileUpload.objects.get().user == user

    def test_fileupload_validation(self):
        self.post()
        upload = FileUpload.objects.filter().order_by('-created').first()
        assert upload.validation
        validation = json.loads(upload.validation)

        assert not validation['success']
        # The current interface depends on this JSON structure:
        assert validation['errors'] == 1
        assert validation['warnings'] == 0
        assert len(validation['messages'])
        msg = validation['messages'][0]
        assert 'uid' in msg, "Unexpected: %r" % msg
        assert msg['type'] == u'error'
        assert msg['message'] == u'The package is not of a recognized type.'
        assert not msg['description'], 'Found unexpected description.'

    def test_redirect(self):
        r = self.post()
        upload = FileUpload.objects.get()
        url = reverse(
            'devhub.upload_detail',
            args=[upload.uuid.hex, 'json'])
        self.assert3xx(r, url)

    @mock.patch('validator.validate.validate')
    def test_upload_unlisted_addon(self, validate_mock):
        """Unlisted addons are validated as "self hosted" addons."""
        validate_mock.return_value = json.dumps(amo.VALIDATOR_SKELETON_RESULTS)
        self.url = reverse('devhub.upload_unlisted')
        self.post()
        # Make sure it was called with listed=False.
        assert not validate_mock.call_args[1]['listed']


class TestUploadDetail(BaseUploadTest):
    fixtures = ['base/appversion', 'base/users']

    def setUp(self):
        super(TestUploadDetail, self).setUp()
        assert self.client.login(email='regular@mozilla.com')

    def create_appversion(self, name, version):
        return AppVersion.objects.create(
            application=amo.APPS[name].id, version=version)

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
            'signing_summary': {'trivial': 1, 'low': 0, 'medium': 0,
                                'high': 0},
            'passed_auto_validation': 1,
            'message_tree': {},
            'messages': [],
            'rejected': False,
            'metadata': {}}

    def upload_file(self, file):
        addon = os.path.join(
            settings.ROOT, 'src', 'olympia', 'devhub', 'tests', 'addons', file)
        with open(addon, 'rb') as f:
            r = self.client.post(reverse('devhub.upload'),
                                 {'upload': f})
        assert r.status_code == 302

    def test_detail_json(self):
        self.post()

        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid.hex, 'json']))
        assert r.status_code == 200
        data = json.loads(r.content)
        assert data['validation']['errors'] == 2
        assert data['url'] == (
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json']))
        assert data['full_report_url'] == (
            reverse('devhub.upload_detail', args=[upload.uuid.hex]))
        assert data['processed_by_addons_linter'] is False
        # We must have tiers
        assert len(data['validation']['messages'])
        msg = data['validation']['messages'][0]
        assert msg['tier'] == 1

    def test_upload_detail_for_version(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = addon_factory()
        addon.addonuser_set.create(user=user)
        self.post()

        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail_for_version',
                                           args=[addon.slug, upload.uuid.hex]))
        assert response.status_code == 200

    def test_upload_detail_for_version_unlisted(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = addon_factory(is_listed=False)
        addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        addon.addonuser_set.create(user=user)
        self.post()

        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail_for_version',
                                           args=[addon.slug, upload.uuid.hex]))
        assert response.status_code == 200

    def test_upload_detail_for_version_deleted(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = addon_factory()
        addon.addonuser_set.create(user=user)
        addon.delete()
        self.post()

        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail_for_version',
                                           args=[addon.slug, upload.uuid.hex]))
        assert response.status_code == 404

    def test_detail_json_addons_linter(self):
        self.upload_file('valid_webextension.xpi')

        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid.hex, 'json']))
        assert r.status_code == 200
        data = json.loads(r.content)
        assert data['processed_by_addons_linter'] is True

    def test_detail_view(self):
        self.post()
        upload = FileUpload.objects.filter().order_by('-created').first()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid.hex]))
        assert r.status_code == 200
        doc = pq(r.content)
        expected = 'Validation Results for animated.png'
        assert doc('header h2').text() == expected

        suite = doc('#addon-validator-suite')
        expected = reverse(
            'devhub.standalone_upload_detail',
            args=[upload.uuid.hex])
        assert suite.attr('data-validateurl') == expected

    @mock.patch('olympia.devhub.tasks.run_validator')
    def check_excluded_platforms(self, xpi, platforms, v):
        v.return_value = json.dumps(self.validation_ok())
        self.upload_file(xpi)
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid.hex, 'json']))
        assert r.status_code == 200
        data = json.loads(r.content)
        assert sorted(data['platforms_to_exclude']) == sorted(platforms)

    def test_multi_app_addon_can_have_all_platforms(self):
        self.check_excluded_platforms('mobile-2.9.10-fx+fn.xpi', [])

    def test_mobile_excludes_desktop_platforms(self):
        self.check_excluded_platforms('mobile-0.1-fn.xpi', [
            str(p) for p in amo.DESKTOP_PLATFORMS])

    def test_android_excludes_desktop_platforms(self):
        # Test native Fennec.
        self.check_excluded_platforms('android-phone.xpi', [
            str(p) for p in amo.DESKTOP_PLATFORMS])

    def test_search_tool_excludes_all_platforms(self):
        self.check_excluded_platforms('searchgeek-20090701.xml', [
            str(p) for p in amo.SUPPORTED_PLATFORMS])

    def test_desktop_excludes_mobile(self):
        self.check_excluded_platforms('desktop.xpi', [
            str(p) for p in amo.MOBILE_PLATFORMS])

    def test_webextension_supports_all_platforms(self):
        self.create_appversion('firefox', '*')
        self.create_appversion('firefox', '42.0')

        # Android is only supported 48+
        self.create_appversion('android', '48.0')
        self.create_appversion('android', '*')

        self.check_excluded_platforms('valid_webextension.xpi', [])

    def test_webextension_android_excluded_if_no_48_support(self):
        self.create_appversion('firefox', '*')
        self.create_appversion('firefox', '42.*')
        self.create_appversion('firefox', '47.*')
        self.create_appversion('firefox', '48.*')
        self.create_appversion('android', '42.*')
        self.create_appversion('android', '47.*')
        self.create_appversion('android', '48.*')
        self.create_appversion('android', '*')

        self.check_excluded_platforms('valid_webextension_max_47.xpi', [
            str(amo.PLATFORM_ANDROID.id)
        ])

    def test_no_servererror_on_missing_version(self):
        """https://github.com/mozilla/addons-server/issues/3779

        addons-linter and amo-validator both add proper errors if the version
        is missing but we shouldn't fail on that but properly show the
        validation results.
        """
        self.upload_file('valid_webextension_no_version.xpi')
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid.hex, 'json']))
        data = json.loads(r.content)
        message = [(m['message'], m.get('type') == 'error')
                   for m in data['validation']['messages']]
        expected = [(u'&#34;/version&#34; is a required property', True)]
        assert message == expected

    @mock.patch('olympia.devhub.tasks.run_validator')
    @mock.patch.object(waffle, 'flag_is_active')
    def test_unparsable_xpi(self, flag_is_active, v):
        flag_is_active.return_value = True
        v.return_value = json.dumps(self.validation_ok())
        self.upload_file('unopenable.xpi')
        upload = FileUpload.objects.get()
        r = self.client.get(reverse('devhub.upload_detail',
                                    args=[upload.uuid.hex, 'json']))
        data = json.loads(r.content)
        message = [(m['message'], m.get('fatal', False))
                   for m in data['validation']['messages']]
        assert message == [(u'Could not parse the manifest file.', True)]

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_experiment_xpi_allowed(self, mock_validator):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        self.grant_permission(user, 'Experiments:submit')
        mock_validator.return_value = json.dumps(self.validation_ok())
        self.upload_file(
            '../../../files/fixtures/files/telemetry_experiment.xpi')
        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail',
                                           args=[upload.uuid.hex, 'json']))
        data = json.loads(response.content)
        assert data['validation']['messages'] == []

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_experiment_xpi_not_allowed(self, mock_validator):
        mock_validator.return_value = json.dumps(self.validation_ok())
        self.upload_file(
            '../../../files/fixtures/files/telemetry_experiment.xpi')
        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail',
                                           args=[upload.uuid.hex, 'json']))
        data = json.loads(response.content)
        assert data['validation']['messages'] == [
            {u'tier': 1, u'message': u'You cannot submit this type of add-on',
             u'fatal': True, u'type': u'error'}]


def assert_json_error(request, field, msg):
    assert request.status_code == 400
    assert request['Content-Type'] == 'application/json'
    field = '__all__' if field is None else field
    content = json.loads(request.content)
    assert field in content, '%r not in %r' % (field, content)
    assert content[field] == [msg]


def assert_json_field(request, field, msg):
    assert request.status_code == 200
    assert request['Content-Type'] == 'application/json'
    content = json.loads(request.content)
    assert field in content, '%r not in %r' % (field, content)
    assert content[field] == msg


class UploadTest(BaseUploadTest, TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(UploadTest, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.addon.update(guid='guid@xpi')
        assert self.client.login(email='del@icio.us')


class TestQueuePosition(UploadTest):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestQueuePosition, self).setUp()

        self.url = reverse('devhub.versions.add_file',
                           args=[self.addon.slug, self.version.id])
        self.edit_url = reverse('devhub.versions.edit',
                                args=[self.addon.slug, self.version.id])
        version_files = self.version.files.all()[0]
        version_files.platform = amo.PLATFORM_LINUX.id
        version_files.save()

    def test_not_in_queue(self):
        r = self.client.get(self.addon.get_dev_url('versions'))

        assert self.addon.status == amo.STATUS_PUBLIC
        assert pq(r.content)('.version-status-actions .dark').length == 0

    def test_in_queue(self):
        statuses = [(amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW),
                    (amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW)]

        for addon_status in statuses:
            self.addon.status = addon_status[0]
            self.addon.save()

            latest_version = self.addon.find_latest_version()
            file = latest_version.files.all()[0]
            file.status = addon_status[1]
            file.save()

            r = self.client.get(self.addon.get_dev_url('versions'))
            doc = pq(r.content)

            span = doc('.queue-position')

            assert span.length
            assert "Queue Position: 1 of 1" in span.text()


class TestVersionAddFile(UploadTest):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestVersionAddFile, self).setUp()
        self.version = self.addon.current_version
        self.version.update(version='0.1')
        self.url = reverse('devhub.versions.add_file',
                           args=[self.addon.slug, self.version.id])
        self.edit_url = reverse('devhub.versions.edit',
                                args=[self.addon.slug, self.version.id])
        version_files = self.version.files.all()[0]
        version_files.update(platform=amo.PLATFORM_LINUX.id,
                             status=amo.STATUS_AWAITING_REVIEW)
        self.addon.update(status=amo.STATUS_NOMINATED)
        # We need to clear the cached properties for platform change above.
        del self.version.supported_platforms
        del self.version.all_files
        # We're going to have a bad time in the tests if we can't upload.
        assert self.version.is_allowed_upload()

    def make_mobile(self):
        for a in self.version.apps.all():
            a.application = amo.ANDROID.id
            a.save()

    def post(self, platform=amo.PLATFORM_MAC, source=None, beta=False):
        return self.client.post(self.url, dict(upload=self.upload.uuid.hex,
                                               platform=platform.id,
                                               source=source, beta=beta))

    def test_guid_matches(self):
        self.addon.update(guid='something.different')
        r = self.post()
        assert_json_error(r, None, (
            "The add-on ID in your manifest.json or install.rdf (guid@xpi) "
            "does not match the ID of your add-on on AMO (something.different)"
        ))

    def test_version_matches(self):
        self.version.update(version='2.0')
        r = self.post()
        assert_json_error(r, None, "Version doesn't match")

    def test_delete_button_enabled(self):
        r = self.client.get(self.edit_url)
        doc = pq(r.content)('#file-list')
        assert doc.find('a.remove').length == 1
        assert doc.find('span.remove.tooltip').length == 0

    def test_delete_button_disabled(self):
        version = self.addon.find_latest_version()
        version.files.all()[0].update(status=amo.STATUS_PUBLIC)

        r = self.client.get(self.edit_url)
        doc = pq(r.content)('#file-list')
        assert doc.find('a.remove').length == 0
        assert doc.find('span.remove.tooltip').length == 1

        tip = doc.find('span.remove.tooltip')
        assert "You cannot remove an individual file" in tip.attr('title')

    def test_delete_button_multiple(self):
        file = self.addon.current_version.files.all()[0]
        file.pk = None
        file.save()

        cases = (
            (amo.STATUS_AWAITING_REVIEW, amo.STATUS_AWAITING_REVIEW, True),
            (amo.STATUS_DISABLED, amo.STATUS_AWAITING_REVIEW, False))

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
        version = self.addon.current_version
        version.files.all()[0].update(status=amo.STATUS_PUBLIC)

        file_id = self.addon.current_version.files.all()[0].id
        platform = amo.PLATFORM_MAC.id
        form = {'DELETE': 'checked', 'id': file_id, 'platform': platform}

        data = formset(form, platform=platform, upload=self.upload.uuid.hex,
                       initial_count=1, prefix='files')

        r = self.client.post(self.edit_url, data)
        doc = pq(r.content)

        assert "You cannot delete a file once" in doc('.errorlist li').text()

    def test_delete_submit_enabled(self):
        file_id = self.addon.current_version.files.all()[0].id
        platform = amo.PLATFORM_MAC.id
        form = {'DELETE': 'checked', 'id': file_id, 'platform': platform}

        data = formset(form, platform=platform, upload=self.upload.uuid.hex,
                       initial_count=1, prefix='files')
        data.update(formset(total_count=1, initial_count=1))

        r = self.client.post(self.edit_url, data)
        doc = pq(r.content)

        assert doc('.errorlist li').length == 0

    def test_platform_limits(self):
        r = self.post(platform=amo.PLATFORM_BSD)
        assert_json_error(r, 'platform',
                          'Select a valid choice. That choice is not one of '
                          'the available choices.')

    def test_platform_choices(self):
        r = self.client.get(self.edit_url)
        form = r.context['new_file_form']
        platform = self.version.files.get().platform
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
        assert sorted(dict(form.fields['platform'].choices).keys()) == (
            sorted([p.id for p in all_choices]))

    def test_platform_choices_when_mobile(self):
        self.make_mobile()
        self.version.files.all().delete()
        r = self.client.get(self.edit_url)
        form = r.context['new_file_form']
        choices = sorted(
            [unicode(c[1]) for c in form.fields['platform'].choices])
        platforms = sorted(
            [unicode(p.name) for p in amo.MOBILE_PLATFORMS.values()])
        assert choices == platforms

    def test_type_matches(self):
        self.addon.update(type=amo.ADDON_THEME)
        r = self.post()
        assert_json_error(r, None, (
            "<em:type> in your install.rdf (1) "
            "does not match the type of your add-on on AMO (2)"
        ))

    def test_file_platform(self):
        # Check that we're creating a new file with the requested platform.
        qs = self.version.files
        assert len(qs.all()) == 1
        assert not qs.filter(platform=amo.PLATFORM_MAC.id)
        self.post()
        assert len(qs.all()) == 2
        assert qs.get(platform=amo.PLATFORM_MAC.id)

    def test_version_deleted(self):
        self.version.delete()
        response = self.post()
        assert response.status_code == 404

    def test_upload_not_found(self):
        r = self.client.post(self.url, dict(upload='xxx',
                                            platform=amo.PLATFORM_MAC.id))
        assert_json_error(r, 'upload',
                          'There was an error with your upload. Please try '
                          'again.')

    @mock.patch('olympia.versions.models.Version.is_allowed_upload')
    def test_cant_upload(self, allowed):
        """Test that if is_allowed_upload fails, the upload will fail."""
        allowed.return_value = False
        res = self.post()
        assert_json_error(res, '__all__',
                          'You cannot upload any more files for this version.')

    def test_success_html(self):
        r = self.post()
        assert r.status_code == 200
        new_file = self.version.files.get(platform=amo.PLATFORM_MAC.id)
        assert r.context['form'].instance == new_file

    def test_with_source(self):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=".zip", dir=tdir)
        source.write('a' * (2 ** 21))
        source.seek(0)
        response = self.post(source=source)
        assert response.status_code == 200
        assert self.addon.versions.get(pk=self.addon.current_version.pk).source
        assert Addon.objects.get(pk=self.addon.pk).admin_review

    def test_with_bad_source_format(self):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=".exe", dir=tdir)
        source.write('a' * (2 ** 21))
        source.seek(0)
        response = self.post(source=source)
        assert response.status_code == 400
        assert 'source' in json.loads(response.content)

    @mock.patch('olympia.editors.helpers.sign_file')
    def test_unlisted_addon_fail_validation(self, mock_sign_file):
        """Files that fail validation are also auto signed/reviewed."""
        self.version.all_files[0].update(status=amo.STATUS_PUBLIC)
        self.addon.update(is_listed=False, status=amo.STATUS_PUBLIC)
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert self.addon.status == amo.STATUS_PUBLIC
        # Make sure the file has validation warnings or errors.
        self.upload.update(
            validation='{"notices": 2, "errors": 0, "messages": [],'
                       ' "metadata": {}, "warnings": 1,'
                       ' "signing_summary": {"trivial": 1, "low": 1,'
                       '                     "medium": 0, "high": 0},'
                       ' "passed_auto_validation": 1}')
        self.post()
        file_ = File.objects.latest()
        # Status is changed to reviewed and the file is signed.
        assert self.addon.status == amo.STATUS_PUBLIC
        assert file_.status == amo.STATUS_PUBLIC
        assert mock_sign_file.called
        # There is a log for that unlisted file signature (with failed
        # validation).
        log = ActivityLog.objects.order_by('pk').last()
        expected = amo.LOG.UNLISTED_SIGNED_VALIDATION_FAILED.id
        assert log.action == expected

    @mock.patch('olympia.editors.helpers.sign_file')
    def test_unlisted_addon_pass_validation(self, mock_sign_file):
        """Files that pass validation are automatically signed/reviewed."""
        self.version.all_files[0].update(status=amo.STATUS_PUBLIC)
        self.addon.update(is_listed=False, status=amo.STATUS_PUBLIC)
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        # Make sure the file has no validation signing related messages.
        self.upload.update(
            validation='{"notices": 2, "errors": 0, "messages": [],'
                       ' "metadata": {}, "warnings": 1,'
                       ' "signing_summary": {"trivial": 1, "low": 0,'
                       '                     "medium": 0, "high": 0},'
                       ' "passed_auto_validation": 1}')
        assert self.addon.status == amo.STATUS_PUBLIC
        self.post()
        file_ = File.objects.latest()
        # Status is changed to reviewed and the file is signed.
        assert self.addon.status == amo.STATUS_PUBLIC
        assert file_.status == amo.STATUS_PUBLIC
        assert mock_sign_file.called
        # There is a log for that unlisted file signature (with passed
        # validation).
        log = ActivityLog.objects.order_by('pk').last()
        expected = amo.LOG.UNLISTED_SIGNED_VALIDATION_PASSED.id
        assert log.action == expected

    @mock.patch('olympia.devhub.views.sign_file')
    def test_beta_addon_pass_validation(self, mock_sign_file):
        """Beta files that pass validation are automatically
        signed/reviewed."""
        # Make sure the file has no validation signing related messages.
        self.upload.update(
            validation='{"notices": 2, "errors": 0, "messages": [],'
                       ' "metadata": {}, "warnings": 1,'
                       ' "signing_summary": {"trivial": 1, "low": 0,'
                       '                     "medium": 0, "high": 0},'
                       ' "passed_auto_validation": 1}')
        # Give the add-on an approved version so it can be public.
        version_factory(addon=self.addon)
        self.addon.update(status=amo.STATUS_PUBLIC)
        existing_file = self.version.all_files[0]
        existing_file.update(status=amo.STATUS_BETA)

        self.post(beta=True)
        new_file = self.version.files.latest('pk')
        # Addon status didn't change and the file is signed.
        assert self.addon.reload().status == amo.STATUS_PUBLIC
        assert new_file.status == amo.STATUS_BETA
        assert new_file != existing_file
        assert mock_sign_file.called

    def test_file_Size_uses_binary_prefix(self):
        response = self.client.get(self.edit_url)
        table = pq(response.content)('#file-list')
        assert '379.0 KiB' in table.find('td').eq(1).text()


class TestUploadErrors(UploadTest):
    fixtures = ['base/users', 'base/addon_3615']
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

    @mock.patch.object(waffle, 'flag_is_active', return_value=True)
    @mock.patch('olympia.devhub.tasks.validate')
    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_version_upload(self, run_validator, validate_, flag_is_active):
        # Load the versions page:
        res = self.client.get(self.addon.get_dev_url('versions'))
        assert res.status_code == 200
        doc = pq(res.content)

        # javascript: upload file:
        upload_url = doc('#upload-addon').attr('data-upload-url')
        with self.xpi() as f:
            res = self.client.post(upload_url, {'upload': f}, follow=True)

        data = json.loads(res.content)
        poll_url = data['url']
        upload = FileUpload.objects.get(uuid=data['upload'])

        # Check that `tasks.validate` has been called with the expected upload.
        validate_.assert_called_with(upload, listed=True)

        # Poll and check that we are still pending validation.
        data = json.loads(self.client.get(poll_url).content)
        assert data.get('validation') == ''

        # Run the actual validation task which was delayed by the mock.
        run_validator.return_value = self.validator_success
        validate(upload, listed=True)

        # And poll to see that we now have the expected validation results.
        data = json.loads(self.client.get(poll_url).content)
        assert data['validation']
        assert not data['validation']['messages'], \
            'Unexpected validation errors: %s' % data['validation']['messages']

    @mock.patch.object(waffle, 'flag_is_active', return_value=True)
    @mock.patch('olympia.devhub.tasks.validate')
    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_dupe_xpi(self, run_validator, validate_, flag_is_active, **kw):
        # Submit a new addon:
        self.client.post(reverse('devhub.submit.agreement'))  # set cookie
        channel = kw.get('channel', 'listed')
        res = self.client.get(reverse('devhub.submit.upload', args=[channel]))
        assert res.status_code == 200
        doc = pq(res.content)

        # javascript: upload file:
        upload_url = doc('#upload-addon').attr('data-upload-url')
        with self.xpi() as f:
            res = self.client.post(upload_url, {'upload': f}, follow=True)

        data = json.loads(res.content)
        poll_url = data['url']
        upload = FileUpload.objects.get(uuid=data['upload'])

        # Check that `tasks.validate` has been called with the expected upload.
        validate_.assert_called_with(upload, listed=(channel == 'listed'))

        # Poll and check that we are still pending validation.
        data = json.loads(self.client.get(poll_url).content)
        assert data.get('validation') == ''

        # Run the actual validation task which was delayed by the mock.
        run_validator.return_value = self.validator_success
        validate(upload, listed=True)

        # And poll to see that we now have the expected validation results.
        data = json.loads(self.client.get(poll_url).content)

        messages = data['validation']['messages']
        assert len(messages) == 1
        assert messages[0]['message'] == u'Duplicate add-on ID found.'

    def test_dupe_xpi_unlisted_addon(self):
        """Submitting an xpi with the same UUID as an unlisted addon."""
        self.addon.update(is_listed=False)
        self.test_dupe_xpi(channel='unlisted')


@override_switch('step-version-upload', active=False)
class AddVersionTest(UploadTest):

    def post(self, supported_platforms=None,
             override_validation=False, expected_status=200, source=None,
             beta=False, nomination_type=None):
        if supported_platforms is None:
            supported_platforms = [amo.PLATFORM_MAC]
        d = dict(upload=self.upload.uuid.hex, source=source,
                 supported_platforms=[p.id for p in supported_platforms],
                 admin_override_validation=override_validation, beta=beta)
        if nomination_type:
            d['nomination_type'] = nomination_type
        r = self.client.post(self.url, d)
        assert r.status_code == expected_status, r.content
        return r

    def setUp(self):
        super(AddVersionTest, self).setUp()
        self.url = reverse('devhub.versions.add', args=[self.addon.slug])


@override_switch('step-version-upload', active=False)
class TestAddVersion(AddVersionTest):

    def test_unique_version_num(self):
        self.version.update(version='0.1')
        r = self.post(expected_status=400)
        assert_json_error(
            r, None, 'Version 0.1 already exists, or was uploaded before.')

    def test_same_version_if_previous_is_rejected(self):
        # We can't re-use the same version number, even if the previous
        # versions have been disabled/rejected.
        self.version.update(version='0.1')
        self.version.files.update(status=amo.STATUS_DISABLED)
        r = self.post(expected_status=400)
        assert_json_error(
            r, None, 'Version 0.1 already exists, or was uploaded before.')

    def test_same_version_if_previous_is_deleted(self):
        # We can't re-use the same version number if the previous
        # versions has been deleted either.
        self.version.update(version='0.1')
        self.version.delete()
        r = self.post(expected_status=400)
        assert_json_error(
            r, None, 'Version 0.1 already exists, or was uploaded before.')

    def test_success(self):
        r = self.post()
        version = self.addon.versions.get(version='0.1')
        assert_json_field(r, 'url',
                          reverse('devhub.versions.edit',
                                  args=[self.addon.slug, version.id]))
        assert version.channel == amo.RELEASE_CHANNEL_LISTED

    def test_incomplete_addon_now_nominated(self):
        """Uploading a new version for an incomplete addon should set it to
        nominated."""
        self.version.delete()
        # Deleting the only version should make it null.
        assert self.addon.status == amo.STATUS_NULL
        self.post()
        self.addon.reload()
        assert self.addon.status == amo.STATUS_NOMINATED

    def test_not_public(self):
        self.post()
        fle = File.objects.latest()
        assert fle.status != amo.STATUS_PUBLIC

    def test_multiple_platforms(self):
        r = self.post(supported_platforms=[amo.PLATFORM_MAC,
                                           amo.PLATFORM_LINUX])
        assert r.status_code == 200
        version = self.addon.versions.get(version='0.1')
        assert len(version.all_files) == 2

    @mock.patch('olympia.devhub.views.auto_sign_file')
    def test_multiple_platforms_unlisted_addon(self, mock_auto_sign_file):
        self.addon.update(is_listed=False)
        r = self.post(supported_platforms=[amo.PLATFORM_MAC,
                                           amo.PLATFORM_LINUX])
        assert r.status_code == 200
        version = self.addon.versions.get(version='0.1')
        assert len(version.all_files) == 2
        mock_auto_sign_file.assert_has_calls(
            [mock.call(f, is_beta=False) for f in version.all_files])

    def test_with_source(self):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=".zip", dir=tdir)
        source.write('a' * (2 ** 21))
        source.seek(0)
        response = self.post(source=source)
        assert response.status_code == 200
        assert self.addon.versions.get(version='0.1').source
        assert Addon.objects.get(pk=self.addon.pk).admin_review

    def test_with_bad_source_format(self):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=".exe", dir=tdir)
        source.write('a' * (2 ** 21))
        source.seek(0)
        response = self.post(source=source, expected_status=400)
        assert 'source' in json.loads(response.content)

    def test_force_beta(self):
        self.post(beta=True)
        f = File.objects.latest()
        assert f.status == amo.STATUS_BETA

    def test_no_force_beta_for_unlisted_addons(self):
        """No beta version for unlisted addons."""
        self.addon.update(is_listed=False)
        self.post(beta=True)
        f = File.objects.latest()
        assert f.status != amo.STATUS_BETA

    @mock.patch('olympia.editors.helpers.sign_file')
    def test_unlisted_addon_fail_validation(self, mock_sign_file):
        """Files that fail validation are also auto signed/reviewed."""
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.addon.update(
            is_listed=False, status=amo.STATUS_NULL)
        # Make sure the file has validation warnings or errors.
        self.upload.update(
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
                "signing_summary": {"trivial": 1, "low": 1,
                                    "medium": 0, "high": 0},
                "passed_auto_validation": 0}))
        self.post()
        file_ = File.objects.latest()
        # Status is changed to reviewed and the file is signed.
        assert self.addon.status == amo.STATUS_NULL
        assert file_.status == amo.STATUS_PUBLIC
        assert file_.version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert mock_sign_file.called
        # There is a log for that unlisted file signature (with failed
        # validation).
        log = ActivityLog.objects.order_by('pk').last()
        assert log.action == amo.LOG.UNLISTED_SIGNED_VALIDATION_FAILED.id

    @mock.patch('olympia.editors.helpers.sign_file')
    def test_unlisted_addon_pass_validation(self, mock_sign_file):
        """Files that pass validation are automatically signed/reviewed."""
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.addon.update(
            is_listed=False, status=amo.STATUS_NULL)
        # Make sure the file has no validation warnings nor errors.
        self.upload.update(
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
                "signing_summary": {"trivial": 1, "low": 0,
                                    "medium": 0, "high": 0},
                "passed_auto_validation": 1}))
        assert self.addon.status == amo.STATUS_NULL
        self.post()
        file_ = File.objects.latest()
        # Status is changed to reviewed and the file is signed.
        assert self.addon.status == amo.STATUS_NULL
        assert file_.status == amo.STATUS_PUBLIC
        assert file_.version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert mock_sign_file.called
        # There is a log for that unlisted file signature (with passed
        # validation).
        log = ActivityLog.objects.order_by('pk').last()
        assert log.action == amo.LOG.UNLISTED_SIGNED_VALIDATION_PASSED.id

    @mock.patch('olympia.devhub.views.sign_file')
    def test_experiments_are_auto_signed(self, mock_sign_file):
        """Experiment extensions (bug 1220097) are auto-signed."""
        # We're going to sign even if it has signing related errors/warnings.
        self.upload = self.get_upload(
            'telemetry_experiment.xpi',
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
                "signing_summary": {"trivial": 1, "low": 0,
                                    "medium": 0, "high": 1},
                "passed_auto_validation": 0}))
        self.addon.update(guid='experiment@xpi', is_listed=True,
                          status=amo.STATUS_PUBLIC)
        self.post()
        # Make sure the file created and signed is for this addon.
        assert mock_sign_file.call_count == 1
        mock_sign_file_call = mock_sign_file.call_args[0]
        signed_file = mock_sign_file_call[0]
        assert signed_file.version.addon == self.addon
        assert signed_file.version.channel == amo.RELEASE_CHANNEL_LISTED
        # There is a log for that beta file signature (with passed validation).
        log = ActivityLog.objects.latest(field_name='id')
        assert log.action == amo.LOG.EXPERIMENT_SIGNED.id

    def test_no_new_version_upload_for_moz_disabled_addon(self):
        # Check the endpoint isn't there for STATUS_DISABLED.
        self.addon.update(status=amo.STATUS_DISABLED)
        self.post(expected_status=403)


@override_switch('step-version-upload', active=False)
class TestAddBetaVersion(AddVersionTest):
    fixtures = ['base/users', 'base/appversion', 'base/addon_3615']

    def setUp(self):
        super(TestAddBetaVersion, self).setUp()

        self.do_upload()

    def do_upload(self):
        self.upload = self.get_upload('extension-0.2b1.xpi')

    def post_additional(self, version, platform=amo.PLATFORM_MAC):
        url = reverse('devhub.versions.add_file',
                      args=[self.addon.slug, version.id])
        return self.client.post(url, dict(upload=self.upload.uuid.hex,
                                          platform=platform.id, beta=True))

    def test_add_multi_file_beta(self):
        r = self.post(supported_platforms=[amo.PLATFORM_MAC], beta=True)

        version = self.addon.versions.all().order_by('-id')[0]

        # Make sure that the first file is beta
        fle = File.objects.all().order_by('-id')[0]
        assert fle.status == amo.STATUS_BETA

        self.do_upload()
        r = self.post_additional(version, platform=amo.PLATFORM_LINUX)
        assert r.status_code == 200

        # Make sure that the additional files are beta
        fle = File.objects.all().order_by('-id')[0]
        assert fle.status == amo.STATUS_BETA

    def test_force_not_beta(self):
        self.post(beta=False)
        f = File.objects.latest()
        assert f.status == amo.STATUS_AWAITING_REVIEW

    @mock.patch('olympia.devhub.views.sign_file')
    def test_listed_beta_pass_validation(self, mock_sign_file):
        self.addon.update(
            is_listed=True, status=amo.STATUS_PUBLIC)
        # Make sure the file has no validation warnings nor errors.
        self.upload.update(
            validation='{"notices": 2, "errors": 0, "messages": [],'
                       ' "metadata": {}, "warnings": 1,'
                       ' "signing_summary": {"trivial": 1, "low": 0,'
                       '                     "medium": 0, "high": 0},'
                       ' "passed_auto_validation": 1}')
        assert self.addon.status == amo.STATUS_PUBLIC
        self.post(beta=True)
        file_ = File.objects.latest()
        assert self.addon.reload().status == amo.STATUS_PUBLIC
        assert file_.status == amo.STATUS_BETA
        assert mock_sign_file.called
        # There is a log for that beta file signature (with passed validation).
        log = ActivityLog.objects.beta_signed_events().get()
        assert log.action == amo.LOG.BETA_SIGNED_VALIDATION_PASSED.id

    @mock.patch('olympia.devhub.views.sign_file')
    def test_listed_beta_do_not_pass_validation(self, mock_sign_file):
        """Beta files that don't pass validation should be logged."""
        self.addon.update(is_listed=True, status=amo.STATUS_PUBLIC)
        # Make sure the file has validation warnings.
        self.upload.update(
            validation='{"notices": 2, "errors": 1, "messages": [],'
                       ' "metadata": {}, "warnings": 1,'
                       ' "signing_summary": {"trivial": 1, "low": 1,'
                       '                     "medium": 0, "high": 0},'
                       ' "passed_auto_validation": 0}')
        assert self.addon.status == amo.STATUS_PUBLIC
        self.post(beta=True)
        file_ = File.objects.latest()
        assert self.addon.reload().status == amo.STATUS_PUBLIC
        assert file_.status == amo.STATUS_BETA
        assert mock_sign_file.called
        # There is a log for that beta file signature (with failed validation).
        log = ActivityLog.objects.beta_signed_events().get()
        assert log.action == amo.LOG.BETA_SIGNED_VALIDATION_FAILED.id


@override_switch('step-version-upload', active=False)
class TestAddVersionValidation(AddVersionTest):

    def login_as_admin(self):
        assert self.client.login(email='admin@mozilla.com')

    def do_upload_non_fatal(self):
        validation = {
            'errors': 1,
            'detected_type': 'extension',
            'success': False,
            'warnings': 0,
            'notices': 0,
            'signing_summary': {'trivial': 1, 'low': 0, 'medium': 0,
                                'high': 0},
            'passed_auto_validation': 1,
            'message_tree': {},
            'ending_tier': 5,
            'messages': [
                {'description': 'The subpackage could not be opened due to '
                                'issues with corruption. Ensure that the file '
                                'is valid.',
                 'type': 'error',
                 'id': [],
                 'file': 'unopenable.jar',
                 'tier': 2,
                 'message': 'Subpackage corrupt.',
                 'uid': '8a3d5854cf0d42e892b3122259e99445',
                 'compatibility_type': None}],
            'metadata': {}}

        self.upload = self.get_upload(
            'validation-error.xpi',
            validation=json.dumps(validation))

        assert not self.upload.valid

    def test_non_admin_validation_override_fails(self):
        self.do_upload_non_fatal()
        self.post(override_validation=True, expected_status=400)

    def test_admin_validation_override(self):
        self.login_as_admin()
        self.do_upload_non_fatal()

        assert not self.addon.admin_review
        self.post(override_validation=True, expected_status=200)

        assert self.addon.reload().admin_review

    def test_admin_validation_sans_override(self):
        self.login_as_admin()
        self.do_upload_non_fatal()
        self.post(override_validation=False, expected_status=400)


class TestVersionXSS(UploadTest):

    def test_unique_version_num(self):
        # Can't use a "/" to close the tag, as we're doing a get_url_path on
        # it, which uses addons.versions, which consumes up to the first "/"
        # encountered.
        self.version.update(
            version='<script>alert("Happy XSS-Xmas");<script>')
        r = self.client.get(reverse('devhub.addons'))
        assert r.status_code == 200
        assert '<script>alert' not in r.content
        assert '&lt;script&gt;alert' in r.content


class TestDeleteAddon(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestDeleteAddon, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = self.addon.get_dev_url('delete')
        self.client.login(email='admin@mozilla.com')

    def test_bad_password(self):
        r = self.client.post(self.url, dict(slug='nope'))
        self.assert3xx(r, self.addon.get_dev_url('versions'))
        assert r.context['title'] == (
            'URL name was incorrect. Add-on was not deleted.')
        assert Addon.objects.count() == 1

    def test_success(self):
        r = self.client.post(self.url, dict(slug='a3615'))
        self.assert3xx(r, reverse('devhub.addons'))
        assert r.context['title'] == 'Add-on deleted.'
        assert Addon.objects.count() == 0


class TestRequestReview(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestRequestReview, self).setUp()
        self.addon = Addon.objects.create(type=1, name='xxx')
        self.version = Version.objects.create(addon=self.addon)
        self.file = File.objects.create(version=self.version,
                                        platform=amo.PLATFORM_ALL.id)
        self.redirect_url = self.addon.get_dev_url('versions')
        self.public_url = reverse('devhub.request-review',
                                  args=[self.addon.slug])
        assert self.client.login(email='admin@mozilla.com')

    def get_addon(self):
        return Addon.objects.get(id=self.addon.id)

    def get_version(self):
        return Version.objects.get(pk=self.version.id)

    def check(self, old_status, url, new_status):
        self.addon.update(status=old_status)
        r = self.client.post(url)
        self.assert3xx(r, self.redirect_url)
        assert self.get_addon().status == new_status

    def check_400(self, url):
        r = self.client.post(url)
        assert r.status_code == 400

    def test_public(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
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
        assert self.get_version().nomination.timetuple()[0:5] == (
            orig_date.timetuple()[0:5])

    def test_renomination_doesnt_reset_nomination_date(self):
        # Nominate:
        self.addon.update(status=amo.STATUS_NOMINATED)
        # Pretend it was nominated in the past:
        orig_date = datetime.now() - timedelta(days=30)
        self.version.update(nomination=orig_date, _signal=False)
        # Reject it:
        self.addon.update(status=amo.STATUS_NULL)
        # Re-nominate:
        self.addon.update(status=amo.STATUS_NOMINATED)
        assert self.get_version().nomination.timetuple()[0:5] == (
            orig_date.timetuple()[0:5])


class TestRedirects(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestRedirects, self).setUp()
        self.base = reverse('devhub.index')
        assert self.client.login(email='admin@mozilla.com')

    def test_edit(self):
        url = self.base + 'addon/edit/3615'
        r = self.client.get(url, follow=True)
        self.assert3xx(r, reverse('devhub.addons.edit', args=['a3615']), 301)

        url = self.base + 'addon/edit/3615/'
        r = self.client.get(url, follow=True)
        self.assert3xx(r, reverse('devhub.addons.edit', args=['a3615']), 301)

    def test_status(self):
        url = self.base + 'addon/status/3615'
        r = self.client.get(url, follow=True)
        self.assert3xx(r, reverse('devhub.addons.versions',
                                  args=['a3615']), 301)

    def test_versions(self):
        url = self.base + 'versions/3615'
        r = self.client.get(url, follow=True)
        self.assert3xx(r, reverse('devhub.addons.versions',
                                  args=['a3615']), 301)


class TestDocs(TestCase):

    def test_doc_urls(self):
        assert '/en-US/developers/docs/' == reverse('devhub.docs', args=[])
        assert '/en-US/developers/docs/te' == reverse(
            'devhub.docs', args=['te'])
        assert '/en-US/developers/docs/te/st', reverse(
            'devhub.docs', args=['te/st'])

        urls = [(reverse('devhub.docs', args=["getting-started"]), 301),
                (reverse('devhub.docs', args=["how-to"]), 301),
                (reverse('devhub.docs', args=["how-to/other-addons"]), 301),
                (reverse('devhub.docs', args=["fake-page"]), 404),
                (reverse('devhub.docs', args=["how-to/fake-page"]), 404),
                (reverse('devhub.docs'), 301)]

        index = reverse('devhub.index')

        for url in urls:
            r = self.client.get(url[0])
            assert r.status_code == url[1]

            if url[1] == 302:  # Redirect to the index page
                self.assert3xx(r, index)


class TestRemoveLocale(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestRemoveLocale, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = reverse('devhub.addons.remove-locale', args=['a3615'])
        assert self.client.login(email='del@icio.us')

    def test_bad_request(self):
        r = self.client.post(self.url)
        assert r.status_code == 400

    def test_success(self):
        self.addon.name = {'en-US': 'woo', 'el': 'yeah'}
        self.addon.save()
        self.addon.remove_locale('el')
        qs = (Translation.objects.filter(localized_string__isnull=False)
              .values_list('locale', flat=True))
        r = self.client.post(self.url, {'locale': 'el'})
        assert r.status_code == 200
        assert sorted(qs.filter(id=self.addon.name_id)) == ['en-US']

    def test_delete_default_locale(self):
        r = self.client.post(self.url, {'locale': self.addon.default_locale})
        assert r.status_code == 400

    def test_remove_version_locale(self):
        version = self.addon.versions.all()[0]
        version.releasenotes = {'fr': 'oui'}
        version.save()

        self.client.post(self.url, {'locale': 'fr'})
        res = self.client.get(reverse('devhub.versions.edit',
                                      args=[self.addon.slug, version.pk]))
        doc = pq(res.content)
        # There's 2 fields, one for en-us, one for init.
        assert len(doc('div.trans textarea')) == 2


class TestXssOnAddonName(amo.tests.TestXss):

    def test_devhub_feed_page(self):
        url = reverse('devhub.feed', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_devhub_addon_edit_page(self):
        url = reverse('devhub.addons.edit', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)

    def test_devhub_version_edit_page(self):
        url = reverse('devhub.versions.edit', args=[self.addon.slug,
                      self.addon.current_version.id])
        self.assertNameAndNoXSS(url)

    def test_devhub_version_list_page(self):
        url = reverse('devhub.addons.versions', args=[self.addon.slug])
        self.assertNameAndNoXSS(url)


class TestNewDevHubLanding(TestCase):

    def test_waffle_flag_inactive(self):
        response = self.client.get(reverse('devhub.index'))

        assert response.status_code == 200

        # This text only exists on the old page.
        assert 'Learn All About Add-ons' in response.content

    def test_waffle_active(self):
        self.create_flag('new-devhub-landing')
        response = self.client.get(reverse('devhub.index'))

        assert response.status_code == 200

        # This text only exists on the old page.
        assert 'Customize Your Firefox' in response.content
