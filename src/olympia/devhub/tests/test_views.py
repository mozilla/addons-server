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
from django.test import RequestFactory
from django.utils.translation import trim_whitespace

import mock
import waffle
from pyquery import PyQuery as pq

from olympia import amo, core, paypal
from olympia.activity.models import ActivityLog
from olympia.amo.tests import TestCase
from olympia.addons.models import (
    Addon, AddonFeatureCompatibility, AddonUser, Charity)
from olympia.amo.templatetags.jinja_helpers import (
    url as url_reverse, datetime_filter)
from olympia.amo.tests import addon_factory, user_factory, version_factory
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.api.models import APIKey, SYMMETRIC_JWT_TYPE
from olympia.applications.models import AppVersion
from olympia.devhub.decorators import dev_required
from olympia.devhub.forms import ContribForm
from olympia.devhub.models import BlogPost
from olympia.files.models import FileUpload
from olympia.files.tests.test_models import UploadTest as BaseUploadTest
from olympia.reviews.models import Review
from olympia.translations.models import delete_translation, Translation
from olympia.users.models import UserProfile
from olympia.versions.models import ApplicationsVersions, Version


class HubTest(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(HubTest, self).setUp()
        self.url = reverse('devhub.index')
        assert self.client.login(email='regular@mozilla.com')
        assert self.client.get(self.url).status_code == 200
        self.user_profile = UserProfile.objects.get(id=999)

    def clone_addon(self, num, addon_id=3615):
        ids = []
        for i in range(num):
            addon = Addon.objects.get(id=addon_id)
            data = {
                'type': addon.type,
                'status': addon.status,
                'name': 'cloned-addon-%s-%s' % (addon_id, i)
            }
            new_addon = addon_factory(**data)
            new_addon.addonuser_set.create(user=self.user_profile)
            ids.append(new_addon.id)
        return ids


class TestDashboard(HubTest):

    def setUp(self):
        super(TestDashboard, self).setUp()
        self.url = reverse('devhub.addons')
        self.themes_url = reverse('devhub.themes')
        assert self.client.get(self.url).status_code == 200
        self.addon = Addon.objects.get(pk=3615)
        self.addon.addonuser_set.create(user=self.user_profile)

    def test_addons_layout(self):
        doc = pq(self.client.get(self.url).content)
        assert doc('title').text() == (
            'Manage My Submissions :: Developer Hub :: Add-ons for Firefox')
        assert doc('.links-footer').length == 1
        assert doc('#copyright').length == 1
        assert doc('#footer-links .mobile-link').length == 0

    def get_action_links(self, addon_id):
        response = self.client.get(self.url)
        doc = pq(response.content)
        selector = '.item[data-addonid="%s"] .item-actions li > a' % addon_id
        links = [a.text.strip() for a in doc(selector)]
        return links

    def test_no_addons(self):
        """Check that no add-ons are displayed for this user."""
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.item item').length == 0

    def test_addon_pagination(self):
        """Check that the correct info. is displayed for each add-on:
        namely, that add-ons are paginated at 10 items per page, and that
        when there is more than one page, the 'Sort by' header and pagination
        footer appear.

        """
        # Create 9 add-ons, there's already one existing from the setUp.
        self.clone_addon(9)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert len(doc('.item .item-info')) == 10
        assert doc('nav.paginator').length == 0

        # Create 5 add-ons.
        self.clone_addon(5)
        response = self.client.get(self.url, {'page': 2})
        doc = pq(response.content)
        assert len(doc('.item .item-info')) == 5
        assert doc('nav.paginator').length == 1

    def test_themes(self):
        """Check themes show on dashboard."""
        # Create 2 themes.
        for x in range(2):
            addon = addon_factory(type=amo.ADDON_PERSONA)
            addon.addonuser_set.create(user=self.user_profile)
        response = self.client.get(self.themes_url)
        doc = pq(response.content)
        assert len(doc('.item .item-info')) == 2

    def test_show_hide_statistics(self):
        # Not disabled by user: show statistics.
        self.addon.update(disabled_by_user=False)
        links = self.get_action_links(self.addon.pk)
        assert 'Statistics' in links, ('Unexpected: %r' % links)

        # Disabled: hide statistics.
        self.addon.update(disabled_by_user=True)
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

        appver = self.addon.current_version.apps.all()[0]
        appver.delete()
        # Addon is not set to be compatible with Firefox, e10s compatibility is
        # not shown.
        doc = pq(self.client.get(self.url).content)
        item = doc('.item[data-addonid="%s"]' % self.addon.id)
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
        response = self.client.get(self.url)
        doc = pq(response.content)

        assert doc('.blog-posts').length == 1
        assert doc('.blog-posts li').length == 5
        assert doc('.blog-posts li a').eq(0).text() == "hi 0"
        assert doc('.blog-posts li a').eq(4).text() == "hi 4"

    def test_sort_created_filter(self):
        response = self.client.get(self.url + '?sort=created')
        doc = pq(response.content)
        assert doc('.item-details').length == 1
        elm = doc('.item-details .date-created')
        assert elm.length == 1
        assert elm.remove('strong').text() == (
            datetime_filter(self.addon.created, '%b %e, %Y'))

    def test_sort_updated_filter(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.item-details').length == 1
        elm = doc('.item-details .date-updated')
        assert elm.length == 1
        assert elm.remove('strong').text() == (
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
        elm = doc('.item-details .date-created')
        assert elm.remove('strong').text() == (
            trim_whitespace(datetime_filter(addon.created)))

    def test_purely_unlisted_addon_are_not_shown_as_incomplete(self):
        self.make_addon_unlisted(self.addon)
        assert self.addon.has_complete_metadata()

        response = self.client.get(self.url)
        doc = pq(response.content)
        # It should not be considered incomplete despite having STATUS_NULL,
        # since it's purely unlisted.
        assert not doc('.incomplete')

        # Rest of the details should be shown, but not the AMO-specific stuff.
        assert not doc('.item-info')
        assert doc('.item-details')

    def test_mixed_versions_addon_with_incomplete_metadata(self):
        self.make_addon_unlisted(self.addon)
        version = version_factory(
            addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED)
        version.update(license=None)
        self.addon.reload()
        assert not self.addon.has_complete_metadata()

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.incomplete').text() == (
            'This add-on is missing some required information before it can be'
            ' submitted for publication.')
        assert doc('form.resume').attr('action') == (
            url_reverse('devhub.request-review', self.addon.slug))
        assert doc('button.link').text() == 'Resume'

    def test_no_versions_addon(self):
        self.addon.current_version.delete()

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.incomplete').text() == (
            "This add-on doesn't have any versions.")

    def test_only_a_beta_version(self):
        beta_version = version_factory(
            addon=self.addon, version='2.0beta',
            file_kw={'status': amo.STATUS_BETA})
        beta_version.update(license=self.addon.current_version.license)
        self.addon.current_version.update(license=None)
        self.addon.current_version.delete()

        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.incomplete').text() == (
            "This add-on doesn't have any approved versions, so its public "
            "pages (including beta versions) are hidden.")


class TestUpdateCompatibility(TestCase):
    fixtures = ['base/users', 'base/addon_4594_a9', 'base/addon_3615']

    def setUp(self):
        super(TestUpdateCompatibility, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.url = reverse('devhub.addons')

        self._versions = amo.FIREFOX.latest_version, amo.ANDROID.latest_version
        amo.FIREFOX.latest_version = amo.ANDROID.latest_version = '3.6.15'

    def tearDown(self):
        amo.FIREFOX.latest_version = amo.ANDROID.latest_version = (
            self._versions)
        super(TestUpdateCompatibility, self).tearDown()

    def test_no_compat(self):
        self.client.logout()
        assert self.client.login(email='admin@mozilla.com')
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert not doc('.item[data-addonid="4594"] li.compat')
        addon = Addon.objects.get(pk=4594)
        response = self.client.get(
            reverse('devhub.ajax.compat.update',
                    args=[addon.slug, addon.current_version.id]))
        assert response.status_code == 404
        response = self.client.get(
            reverse('devhub.ajax.compat.status', args=[addon.slug]))
        assert response.status_code == 404

    def test_compat(self):
        addon = Addon.objects.get(pk=3615)
        response = self.client.get(self.url)
        doc = pq(response.content)
        cu = doc('.item[data-addonid="3615"] .tooltip.compat-update')
        assert not cu

        addon.current_version.files.update(strict_compatibility=True)
        response = self.client.get(self.url)
        doc = pq(response.content)
        cu = doc('.item[data-addonid="3615"] .tooltip.compat-update')
        assert cu

        update_url = reverse('devhub.ajax.compat.update',
                             args=[addon.slug, addon.current_version.id])
        assert cu.attr('data-updateurl') == update_url

        status_url = reverse('devhub.ajax.compat.status', args=[addon.slug])
        selector = '.item[data-addonid="3615"] li.compat'
        assert doc(selector).attr('data-src') == status_url

        assert doc('.item[data-addonid="3615"] .compat-update-modal')

    def test_incompat_firefox(self):
        addon = Addon.objects.get(pk=3615)
        addon.current_version.files.update(strict_compatibility=True)
        versions = ApplicationsVersions.objects.all()[0]
        versions.max = AppVersion.objects.get(version='2.0')
        versions.save()
        doc = pq(self.client.get(self.url).content)
        assert doc('.item[data-addonid="3615"] .tooltip.compat-error')

    def test_incompat_android(self):
        addon = Addon.objects.get(pk=3615)
        addon.current_version.files.update(strict_compatibility=True)
        appver = AppVersion.objects.get(version='2.0')
        appver.update(application=amo.ANDROID.id)
        av = ApplicationsVersions.objects.all()[0]
        av.application = amo.ANDROID.id
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
        data = json.loads(self.client.get(url).content)
        exp = {str(version.id):
               {'reviews': 10, 'files': 1, 'version': version.version,
                'id': version.id}}
        self.assertDictEqual(data, exp)


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
        data = dict(*args, **kw)
        assert self.client.post(self.url, data).status_code == 302

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
        data = {
            'recipient': 'org',
            'suggested_amount': 11.5,
            'annoying': amo.CONTRIB_PASSIVE,
            'charity-name': 'fligtar fund',
            'charity-url': 'http://feed.me',
            'charity-paypal': 'greed@org'
        }
        self.post(data)
        self.check(paypal_id='', suggested_amount=Decimal('11.50'),
                   charity=Charity.objects.get(name='fligtar fund'))

    def test_dev_paypal_id_length(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert int(doc('#id_paypal_id').attr('size')) == 50

    def test_dev_paypal_reqd(self):
        data = {
            'recipient': 'dev',
            'suggested_amount': 2,
            'annoying': amo.CONTRIB_PASSIVE
        }
        response = self.client.post(self.url, data)
        self.assertFormError(response, 'contrib_form', 'paypal_id',
                             'PayPal ID required to accept contributions.')

    def test_bad_paypal_id_dev(self):
        self.paypal_mock.return_value = False, 'error'
        data = {
            'recipient': 'dev',
            'suggested_amount': 2,
            'annoying': amo.CONTRIB_AFTER,
            'paypal_id': 'greed@dev',
        }
        response = self.client.post(self.url, data)
        self.assertFormError(response, 'contrib_form', 'paypal_id', 'error')

    def test_bad_paypal_id_charity(self):
        self.paypal_mock.return_value = False, 'error'
        data = {
            'recipient': 'org',
            'suggested_amount': 11.5,
            'annoying': amo.CONTRIB_PASSIVE,
            'charity-name': 'fligtar fund',
            'charity-url': 'http://feed.me',
            'charity-paypal': 'greed@org'
        }
        response = self.client.post(self.url, data)
        self.assertFormError(response, 'charity_form', 'paypal', 'error')

    def test_paypal_timeout(self):
        self.paypal_mock.side_effect = socket.timeout()
        data = {
            'recipient': 'dev',
            'suggested_amount': 2,
            'paypal_id': 'greed@dev',
            'annoying': amo.CONTRIB_AFTER
        }
        response = self.client.post(self.url, data)
        self.assertFormError(response, 'contrib_form', 'paypal_id',
                             'Could not validate PayPal id.')

    def test_max_suggested_amount(self):
        too_much = settings.MAX_CONTRIBUTION + 1
        msg = ('Please enter a suggested amount less than $%d.' %
               settings.MAX_CONTRIBUTION)
        response = self.client.post(self.url, {'suggested_amount': too_much})
        self.assertFormError(response, 'contrib_form', 'suggested_amount', msg)

    def test_neg_suggested_amount(self):
        msg = 'Please enter a suggested amount greater than 0.'
        response = self.client.post(self.url, {'suggested_amount': -1})
        self.assertFormError(response, 'contrib_form', 'suggested_amount', msg)

    def test_charity_details_reqd(self):
        data = {
            'recipient': 'org',
            'suggested_amount': 11.5,
            'annoying': amo.CONTRIB_PASSIVE
        }
        response = self.client.post(self.url, data)
        self.assertFormError(response, 'charity_form', 'name',
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
        data = {
            'enable_thankyou': 'on',
            'thankyou_note': 'woo',
            'annoying': 1,
            'recipient': 'moz'
        }
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        addon = self.get_addon()
        assert addon.enable_thankyou
        assert unicode(addon.thankyou_note) == 'woo'

    def test_enable_thankyou_unchecked_with_text(self):
        data = {
            'enable_thankyou': '',
            'thankyou_note': 'woo',
            'annoying': 1,
            'recipient': 'moz'
        }
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        addon = self.get_addon()
        assert not addon.enable_thankyou
        assert addon.thankyou_note is None

    def test_contribution_link(self):
        self.test_success_foundation()
        response = self.client.get(self.url)
        doc = pq(response.content)

        span = doc('#status-bar').find('span')
        assert span.length == 1
        assert span.text().startswith('Your contribution page: ')

        link = span.find('a')
        assert link.length == 1
        assert link.attr('href') == reverse(
            'addons.about', args=[self.get_addon().slug])
        assert link.text() == url_reverse(
            'addons.about', self.get_addon().slug, host=settings.SITE_URL)

    def test_enable_thankyou_no_text(self):
        data = {
            'enable_thankyou': 'on',
            'thankyou_note': '',
            'annoying': 1,
            'recipient': 'moz'
        }
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        addon = self.get_addon()
        assert not addon.enable_thankyou
        assert addon.thankyou_note is None

    def test_no_future(self):
        self.get_addon().update(the_future=None)
        response = self.client.get(self.url)
        error_msg = pq(response.content)('p.error').text()
        assert 'completed developer profile' in error_msg

    def test_addon_public(self):
        self.get_addon().update(status=amo.STATUS_PUBLIC)
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('#do-setup').text() == 'Set up Contributions'

    def test_voluntary_contributions_addons(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.intro').length == 1
        assert doc('.intro.full-intro').length == 0

    def test_no_voluntary_contributions_for_unlisted_addons(self):
        self.make_addon_unlisted(self.addon)
        response = self.client.get(self.url)
        doc = pq(response.content)
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
        response = self.client.get(self.pay_url)
        self.assertContains(response, '<div id="status-bar">')

        self.addon.update(wants_contributions=False)
        response = self.client.get(self.pay_url)
        self.assertNotContains(response, '<div id="status-bar">')

    def test_disable(self):
        response = self.client.post(self.disable_url)
        assert response.status_code == 302
        assert(response['Location'].endswith(self.pay_url))
        assert not Addon.objects.no_cache().get(id=3615).wants_contributions


class TestPaymentsProfile(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestPaymentsProfile, self).setUp()
        self.addon = self.get_addon()
        self.url = self.addon.get_dev_url('payments')
        # Make sure all the payment/profile data is clear.
        assert not (
            self.addon.wants_contributions or
            self.addon.paypal_id or
            self.addon.the_reason or
            self.addon.the_future or
            self.addon.takes_contributions)
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
        data = {
            'recipient': 'dev',
            'suggested_amount': 2,
            'paypal_id': 'xx@yy',
            'annoying': amo.CONTRIB_ROADBLOCK,
            'the_reason': 'xxx',
            'the_future': 'yyy'
        }
        response = self.client.post(self.url, data)
        assert response.status_code == 302

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

        data = {
            'recipient': 'dev',
            'suggested_amount': 2,
            'paypal_id': 'xx@yy',
            'annoying': amo.CONTRIB_ROADBLOCK
        }
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        self.assertFormError(response, 'profile_form', 'the_reason',
                             'This field is required.')
        self.assertFormError(response, 'profile_form', 'the_future',
                             'This field is required.')
        check_page(response)
        assert not self.get_addon().wants_contributions

        data = {
            'recipient': 'dev',
            'suggested_amount': 2,
            'paypal_id': 'xx@yy',
            'annoying': amo.CONTRIB_ROADBLOCK,
            'the_reason': 'xxx'
        }
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        self.assertFormError(response, 'profile_form', 'the_future',
                             'This field is required.')
        check_page(response)
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
        response = self.client.post(self.get_url(), follow=True)
        assert pq(response.content)('.notification-box').text() == (
            'URL name was incorrect. Add-on was not deleted.')
        assert self.get_addon().exists()

    def test_post(self):
        self.get_addon().get().update(slug='addon-slug')
        response = self.client.post(self.get_url(), {'slug': 'addon-slug'},
                                    follow=True)
        assert pq(response.content)('.notification-box').text() == (
            'Add-on deleted.')
        assert not self.get_addon().exists()

    def test_post_wrong_slug(self):
        self.get_addon().get().update(slug='addon-slug')
        response = self.client.post(self.get_url(), {'slug': 'theme-slug'},
                                    follow=True)
        assert pq(response.content)('.notification-box').text() == (
            'URL name was incorrect. Add-on was not deleted.')
        assert self.get_addon().exists()

    def test_post_theme(self):
        theme = self.make_theme()
        response = self.client.post(
            theme.get_dev_url('delete'), {'slug': 'theme-slug'}, follow=True)
        assert pq(response.content)('.notification-box').text() == (
            'Theme deleted.')
        assert not Addon.objects.filter(id=theme.id).exists()

    def test_post_theme_wrong_slug(self):
        theme = self.make_theme()
        response = self.client.post(
            theme.get_dev_url('delete'), {'slug': 'addon-slug'}, follow=True)
        assert pq(response.content)('.notification-box').text() == (
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
        response = self.client.get(self.url)
        assert response.status_code == 200
        return pq(response.content)

    def test_basic_logged_out(self):
        self.client.logout()
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'devhub/index.html')
        assert 'Customize Firefox' in response.content

    def test_default_lang_selected(self):
        self.client.logout()
        doc = self.get_pq()
        selected_value = doc('#language option:selected').attr('value')
        assert selected_value == 'en-us'

    def test_basic_logged_in(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        self.assertTemplateUsed(response, 'devhub/index.html')
        assert 'My Add-ons' in response.content

    def test_my_addons_addon_versions_link(self):
        assert self.client.login(email='del@icio.us')

        doc = self.get_pq()
        addon_list = doc('.DevHub-MyAddons-list')

        href = addon_list.find('.DevHub-MyAddons-item-versions a').attr('href')
        assert href == self.addon.get_dev_url('versions')

    def test_my_addons_persona_versions_link(self):
        """References https://github.com/mozilla/addons-server/issues/4283

        Make sure that a call to a persona doesn't result in a 500."""
        assert self.client.login(email='del@icio.us')
        user_profile = UserProfile.objects.get(email='del@icio.us')
        addon_factory(type=amo.ADDON_PERSONA, users=[user_profile])

        doc = self.get_pq()
        addon_list = doc('.DevHub-MyAddons-list')
        assert len(addon_list.find('.DevHub-MyAddons-item')) == 2

        span_text = (
            addon_list.find('.DevHub-MyAddons-item')
            .eq(0)
            .find('span.DevHub-MyAddons-VersionStatus').text())

        assert span_text == 'Approved'

    def test_my_addons(self):
        statuses = [
            (amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW,
                'Awaiting Review'),
            (amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW,
                'Approved'),
            (amo.STATUS_DISABLED, amo.STATUS_PUBLIC,
                'Disabled by Mozilla')]

        for addon_status, file_status, status_str in statuses:
            latest_version = self.addon.find_latest_version(
                amo.RELEASE_CHANNEL_LISTED)
            file = latest_version.files.all()[0]
            file.update(status=file_status)

            self.addon.update(status=addon_status)

            doc = self.get_pq()
            addon_item = doc('.DevHub-MyAddons-list .DevHub-MyAddons-item')
            assert addon_item.length == 1
            assert (
                addon_item.find('.DevHub-MyAddons-item-edit').attr('href') ==
                self.addon.get_dev_url('edit'))

            assert (
                status_str ==
                addon_item.find('.DevHub-MyAddons-VersionStatus').text())

        Addon.objects.all().delete()
        assert self.get_pq()(
            '.DevHub-MyAddons-list .DevHub-MyAddons-item').length == 0

    def test_my_addons_incomplete(self):
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.categories.all().delete()  # Make add-on incomplete
        doc = self.get_pq()
        addon_item = doc('.DevHub-MyAddons-list .DevHub-MyAddons-item')
        assert addon_item.length == 1
        assert (
            addon_item.find('.DevHub-MyAddons-item-edit').attr('href') ==
            self.addon.get_dev_url('edit'))

    def test_my_addons_no_disabled_or_deleted(self):
        self.addon.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        doc = self.get_pq()

        addon_item = doc('.DevHub-MyAddons-list .DevHub-MyAddons-item')
        assert addon_item.length == 1
        assert (
            addon_item.find('.DevHub-MyAddons-VersionStatus').text() ==
            'Invisible')


class TestActivityFeed(TestCase):
    fixtures = ('base/users', 'base/addon_3615')

    def setUp(self):
        super(TestActivityFeed, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.versions.first()

    def test_feed_for_all(self):
        response = self.client.get(reverse('devhub.feed_all'))
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('header h2').text() == 'Recent Activity for My Add-ons'

    def test_feed_for_addon(self):
        response = self.client.get(
            reverse('devhub.feed', args=[self.addon.slug]))
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('header h2').text() == (
            'Recent Activity for %s' % self.addon.name)

    def test_feed_disabled(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        response = self.client.get(
            reverse('devhub.feed', args=[self.addon.slug]))
        assert response.status_code == 200

    def test_feed_disabled_anon(self):
        self.client.logout()
        response = self.client.get(
            reverse('devhub.feed', args=[self.addon.slug]))
        assert response.status_code == 302

    def add_log(self, action=amo.LOG.ADD_REVIEW):
        core.set_user(UserProfile.objects.get(email='del@icio.us'))
        ActivityLog.create(action, self.addon, self.version)

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
        self.make_addon_unlisted(self.addon)
        self.add_log()
        res = self.client.get(reverse('devhub.addons'))
        doc = pq(res.content)
        assert len(doc('.recent-activity li.item')) == 1

    def test_unlisted_addons_feed_sidebar(self):
        """Unlisted addons are displayed in the left side in the feed page."""
        self.make_addon_unlisted(self.addon)
        self.add_log()
        res = self.client.get(reverse('devhub.feed_all'))
        doc = pq(res.content)
        # First li is "All My Add-ons".
        assert len(doc('#refine-addon li')) == 2

    def test_unlisted_addons_feed(self):
        """Unlisted addons are displayed in the feed page."""
        self.make_addon_unlisted(self.addon)
        self.add_log()
        res = self.client.get(reverse('devhub.feed_all'))
        doc = pq(res.content)
        assert len(doc('#recent-activity .item')) == 1

    def test_unlisted_addons_feed_filter(self):
        """Feed page can be filtered on unlisted addon."""
        self.make_addon_unlisted(self.addon)
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
        data = dict(*args, **kw)
        assert self.client.post(self.url, data).status_code == 302

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
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)
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
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('label[for=the_reason] .req').length, (
            'the_reason field should be required.')
        assert doc('label[for=the_future] .req').length, (
            'the_future field should be required.')

    def test_log(self):
        self.enable_addon_contributions()
        data = {'the_reason': 'because', 'the_future': 'i can'}
        assert ActivityLog.objects.count() == 0
        self.client.post(self.url, data)
        assert ActivityLog.objects.filter(
            action=amo.LOG.EDIT_PROPERTIES.id).count() == 1

    def test_with_contributions_fields_required(self):
        self.enable_addon_contributions()

        data = {'the_reason': '', 'the_future': ''}
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        self.assertFormError(response, 'profile_form', 'the_reason',
                             'This field is required.')
        self.assertFormError(response, 'profile_form', 'the_future',
                             'This field is required.')

        data = {'the_reason': 'to be cool', 'the_future': ''}
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        self.assertFormError(response, 'profile_form', 'the_future',
                             'This field is required.')

        data = {'the_reason': '', 'the_future': 'hot stuff'}
        response = self.client.post(self.url, data)
        assert response.status_code == 200
        self.assertFormError(response, 'profile_form', 'the_reason',
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
        response = self.post()
        assert response.status_code == 302

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
        response = self.post()
        upload = FileUpload.objects.get()
        url = reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json'])
        self.assert3xx(response, url)

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
            'message_tree': {},
            'messages': [],
            'rejected': False,
            'metadata': {}}

    def upload_file(self, file):
        addon = os.path.join(
            settings.ROOT, 'src', 'olympia', 'devhub', 'tests', 'addons', file)
        with open(addon, 'rb') as f:
            response = self.client.post(
                reverse('devhub.upload'), {'upload': f})
        assert response.status_code == 302

    def test_detail_json(self):
        self.post()

        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail',
                                   args=[upload.uuid.hex, 'json']))
        assert response.status_code == 200
        data = json.loads(response.content)
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
        addon = addon_factory(
            version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED})
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
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json']))
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['processed_by_addons_linter'] is True

    def test_detail_view(self):
        self.post()
        upload = FileUpload.objects.filter().order_by('-created').first()
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex]))
        assert response.status_code == 200
        doc = pq(response.content)
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
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json']))
        assert response.status_code == 200
        data = json.loads(response.content)
        assert sorted(data['platforms_to_exclude']) == sorted(platforms)

    def test_multi_app_addon_can_have_all_platforms(self):
        self.check_excluded_platforms('mobile-2.9.10-fx+fn.xpi', [])

    def test_android_excludes_desktop_platforms(self):
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
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json']))
        data = json.loads(response.content)
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
        response = self.client.get(
            reverse('devhub.upload_detail', args=[upload.uuid.hex, 'json']))
        data = json.loads(response.content)
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

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_system_addon_allowed(self, mock_validator):
        user_factory(email='redpanda@mozilla.com')
        assert self.client.login(email='redpanda@mozilla.com')
        mock_validator.return_value = json.dumps(self.validation_ok())
        self.upload_file(
            '../../../files/fixtures/files/mozilla_guid.xpi')
        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail',
                                           args=[upload.uuid.hex, 'json']))
        data = json.loads(response.content)
        assert data['validation']['messages'] == []

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_system_addon_not_allowed_not_mozilla(self, mock_validator):
        user_factory(email='bluepanda@notzilla.com')
        assert self.client.login(email='bluepanda@notzilla.com')
        self.upload_file(
            '../../../files/fixtures/files/mozilla_guid.xpi')
        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail',
                                           args=[upload.uuid.hex, 'json']))
        data = json.loads(response.content)
        assert data['validation']['messages'] == [
            {u'tier': 1, u'message': u'You cannot submit an add-on with a '
                                     u'guid ending "@mozilla.org"',
             u'fatal': True, u'type': u'error'}]

    @mock.patch('olympia.devhub.tasks.run_validator')
    @mock.patch('olympia.files.utils.get_signer_organizational_unit_name')
    def test_mozilla_signed_allowed(self, mock_validator, mock_get_signature):
        user_factory(email='redpanda@mozilla.com')
        assert self.client.login(email='redpanda@mozilla.com')
        mock_validator.return_value = json.dumps(self.validation_ok())
        mock_get_signature.return_value = "Mozilla Extensions"
        self.upload_file(
            '../../../files/fixtures/files/webextension_signed_already.xpi')
        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail',
                                           args=[upload.uuid.hex, 'json']))
        data = json.loads(response.content)
        assert data['validation']['messages'] == []

    @mock.patch('olympia.files.utils.get_signer_organizational_unit_name')
    def test_mozilla_signed_not_allowed_not_mozilla(self, mock_get_signature):
        user_factory(email='bluepanda@notzilla.com')
        assert self.client.login(email='bluepanda@notzilla.com')
        mock_get_signature.return_value = 'Mozilla Extensions'
        self.upload_file(
            '../../../files/fixtures/files/webextension_signed_already.xpi')
        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail',
                                           args=[upload.uuid.hex, 'json']))
        data = json.loads(response.content)
        assert data['validation']['messages'] == [
            {u'tier': 1,
             u'message': u'You cannot submit a Mozilla Signed Extension',
             u'fatal': True, u'type': u'error'}]

    @mock.patch('olympia.devhub.tasks.run_validator')
    def test_system_addon_update_allowed(self, mock_validator):
        """Updates to system addons are allowed from anyone."""
        user = user_factory(email='pinkpanda@notzilla.com')
        addon = addon_factory(guid='systemaddon@mozilla.org')
        AddonUser.objects.create(addon=addon, user=user)
        assert self.client.login(email='pinkpanda@notzilla.com')
        mock_validator.return_value = json.dumps(self.validation_ok())
        self.upload_file(
            '../../../files/fixtures/files/mozilla_guid.xpi')
        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail_for_version',
                                           args=[addon.slug, upload.uuid.hex]))
        print response.content
        data = json.loads(response.content)
        assert data['validation']['messages'] == []

    def test_no_redirect_for_metadata(self):
        user = UserProfile.objects.get(email='regular@mozilla.com')
        addon = addon_factory(status=amo.STATUS_NULL)
        addon.categories.all().delete()
        addon.addonuser_set.create(user=user)
        self.post()

        upload = FileUpload.objects.get()
        response = self.client.get(reverse('devhub.upload_detail_for_version',
                                           args=[addon.slug, upload.uuid.hex]))
        assert response.status_code == 200


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


class TestQueuePosition(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestQueuePosition, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.addon.update(guid='guid@xpi')
        assert self.client.login(email='del@icio.us')

        self.edit_url = reverse('devhub.versions.edit',
                                args=[self.addon.slug, self.version.id])
        version_files = self.version.files.all()[0]
        version_files.platform = amo.PLATFORM_LINUX.id
        version_files.save()

    def test_not_in_queue(self):
        response = self.client.get(self.addon.get_dev_url('versions'))

        assert self.addon.status == amo.STATUS_PUBLIC
        assert (
            pq(response.content)('.version-status-actions .dark').length == 0)

    def test_in_queue(self):
        statuses = [(amo.STATUS_NOMINATED, amo.STATUS_AWAITING_REVIEW),
                    (amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW)]

        for addon_status in statuses:
            self.addon.status = addon_status[0]
            self.addon.save()

            latest_version = self.addon.find_latest_version(
                amo.RELEASE_CHANNEL_LISTED)
            file = latest_version.files.all()[0]
            file.status = addon_status[1]
            file.save()

            response = self.client.get(self.addon.get_dev_url('versions'))
            doc = pq(response.content)

            span = doc('.queue-position')

            assert span.length
            assert "Queue Position: 1 of 1" in span.text()


class TestVersionXSS(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestVersionXSS, self).setUp()
        self.version = Addon.objects.get(id=3615).current_version
        assert self.client.login(email='del@icio.us')

    def test_unique_version_num(self):
        # Can't use a "/" to close the tag, as we're doing a get_url_path on
        # it, which uses addons.versions, which consumes up to the first "/"
        # encountered.
        self.version.update(
            version='<script>alert("Happy XSS-Xmas");<script>')
        response = self.client.get(reverse('devhub.addons'))
        assert response.status_code == 200
        assert '<script>alert' not in response.content
        assert '&lt;script&gt;alert' in response.content


class TestDeleteAddon(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestDeleteAddon, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = self.addon.get_dev_url('delete')
        self.client.login(email='admin@mozilla.com')

    def test_bad_password(self):
        response = self.client.post(self.url, {'slug': 'nope'})
        self.assert3xx(response, self.addon.get_dev_url('versions'))
        assert response.context['title'] == (
            'URL name was incorrect. Add-on was not deleted.')
        assert Addon.objects.count() == 1

    def test_success(self):
        response = self.client.post(self.url, {'slug': 'a3615'})
        self.assert3xx(response, reverse('devhub.addons'))
        assert response.context['title'] == 'Add-on deleted.'
        assert Addon.objects.count() == 0


class TestRequestReview(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestRequestReview, self).setUp()
        self.addon = addon_factory()
        self.version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        self.redirect_url = self.addon.get_dev_url('versions')
        self.public_url = reverse('devhub.request-review',
                                  args=[self.addon.slug])
        assert self.client.login(email='admin@mozilla.com')

    def get_addon(self):
        return Addon.objects.get(id=self.addon.id)

    def get_version(self):
        return Version.objects.get(pk=self.version.id)

    def check_400(self, url):
        response = self.client.post(url)
        assert response.status_code == 400

    def test_public(self):
        self.addon.update(status=amo.STATUS_PUBLIC)
        self.check_400(self.public_url)

    @mock.patch('olympia.addons.models.Addon.has_complete_metadata')
    def test_renominate_for_full_review(self, mock_has_complete_metadata):
        # When a version is rejected, the addon is disabled.
        # The author must upload a new version and re-nominate.
        # Renominating the same version resets the nomination date.
        mock_has_complete_metadata.return_value = True

        orig_date = datetime.now() - timedelta(days=30)
        # Pretend it was nominated in the past:
        self.version.update(nomination=orig_date)
        self.addon.update(status=amo.STATUS_NULL)
        response = self.client.post(self.public_url)
        self.assert3xx(response, self.redirect_url)
        assert self.get_addon().status == amo.STATUS_NOMINATED
        assert self.get_version().nomination.timetuple()[0:5] != (
            orig_date.timetuple()[0:5])


class TestRedirects(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestRedirects, self).setUp()
        self.base = reverse('devhub.index')
        assert self.client.login(email='admin@mozilla.com')

    def test_edit(self):
        url = self.base + 'addon/edit/3615'
        response = self.client.get(url, follow=True)
        self.assert3xx(
            response, reverse('devhub.addons.edit', args=['a3615']), 301)

        url = self.base + 'addon/edit/3615/'
        response = self.client.get(url, follow=True)
        self.assert3xx(
            response, reverse('devhub.addons.edit', args=['a3615']), 301)

    def test_status(self):
        url = self.base + 'addon/status/3615'
        response = self.client.get(url, follow=True)
        self.assert3xx(
            response, reverse('devhub.addons.versions', args=['a3615']), 301)

    def test_versions(self):
        url = self.base + 'versions/3615'
        response = self.client.get(url, follow=True)
        self.assert3xx(
            response, reverse('devhub.addons.versions', args=['a3615']), 301)


class TestHasCompleteMetadataRedirects(TestCase):
    """Make sure Addons that are not complete in some way are correctly
    redirected to the right view (and don't end up in a redirect loop)."""

    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestHasCompleteMetadataRedirects, self).setUp()
        self.f = mock.Mock()
        self.f.__name__ = 'function'
        self.request = RequestFactory().get('developers/addon/a3615/edit')
        self.request.user = UserProfile.objects.get(email='admin@mozilla.com')
        self.addon = Addon.objects.get(id=3615)
        self.addon.update(status=amo.STATUS_NULL)
        self.addon = Addon.objects.get(id=3615)
        assert self.addon.has_complete_metadata(), (
            self.addon.get_required_metadata())
        assert not self.addon.should_redirect_to_submit_flow()
        # We need to be logged in for any redirection into real views.
        assert self.client.login(email='admin@mozilla.com')

    def _test_redirect(self):
        func = dev_required(self.f)
        response = func(self.request, addon_id='a3615')
        assert not self.f.called
        assert response.status_code == 302
        assert response['Location'] == (
            '/en-US/developers/addon/a3615/submit/details')
        # Check the redirection doesn't redirect also.
        redirection = self.client.get(response['Location'])
        assert redirection.status_code == 200

    def test_default(self):
        func = dev_required(self.f)
        func(self.request, addon_id='a3615')
        # Don't redirect if there is no metadata to collect.
        assert self.f.called

    def test_no_summary(self):
        delete_translation(self.addon, 'summary')
        self._test_redirect()

    def test_no_license(self):
        self.addon.current_version.update(license=None)
        self._test_redirect()

    def test_no_license_no_summary(self):
        self.addon.current_version.update(license=None)
        delete_translation(self.addon, 'summary')
        self._test_redirect()


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
            response = self.client.get(url[0])
            assert response.status_code == url[1]

            if url[1] == 302:  # Redirect to the index page
                self.assert3xx(response, index)


class TestRemoveLocale(TestCase):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestRemoveLocale, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.url = reverse('devhub.addons.remove-locale', args=['a3615'])
        assert self.client.login(email='del@icio.us')

    def test_bad_request(self):
        response = self.client.post(self.url)
        assert response.status_code == 400

    def test_success(self):
        self.addon.name = {'en-US': 'woo', 'el': 'yeah'}
        self.addon.save()
        self.addon.remove_locale('el')
        qs = (Translation.objects.filter(localized_string__isnull=False)
              .values_list('locale', flat=True))
        response = self.client.post(self.url, {'locale': 'el'})
        assert response.status_code == 200
        assert sorted(qs.filter(id=self.addon.name_id)) == ['en-US']

    def test_delete_default_locale(self):
        response = self.client.post(
            self.url, {'locale': self.addon.default_locale})
        assert response.status_code == 400

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
