# -*- coding: utf-8 -*-
import hashlib
import json
import os
import zipfile

from django.conf import settings
from django.core import mail
from django.core.files.storage import default_storage as storage
from django.utils.html import strip_tags

import mock
from nose import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
from tower import strip_whitespace
import waffle

import amo
import amo.tests
from abuse.models import AbuseReport
from access.models import GroupUser
from addons.models import AddonCategory, AddonUpsell, AddonUser, Category
from amo.helpers import external_url, urlparams
from amo.urlresolvers import reverse
from devhub.models import ActivityLog
from market.models import PreApprovalUser
from users.models import UserProfile
from versions.models import Version

import mkt
from mkt.webapps.models import AddonExcludedRegion, Webapp


def get_clean(selection):
    return strip_whitespace(str(selection))


class DetailBase(amo.tests.WebappTestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(DetailBase, self).setUp()
        self.url = self.app.get_detail_url()

    def get_user(self):
        return UserProfile.objects.get(email='regular@mozilla.com')

    def get_pq(self, **kw):
        r = self.client.get(self.url, kw)
        eq_(r.status_code, 200)
        return pq(r.content.decode('utf-8'))


class TestDetail(DetailBase):

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_categories(self):
        # We don't show categories on detail pages
        raise SkipTest
        cat = Category.objects.create(name='Lifestyle', slug='lifestyle',
                                      type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=self.app, category=cat)
        links = self.get_pq()('.cats a')
        eq_(links.length, 1)
        eq_(links.attr('href'), cat.get_url_path())
        eq_(links.text(), cat.name)

    def test_free_install_button_for_anon(self):
        doc = self.get_pq()
        eq_(doc('.button.product').length, 1)

    def test_free_install_button_for_owner(self):
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(doc('.button.product').length, 1)
        eq_(doc('.manage').length, 1)

    def test_free_install_button_for_dev(self):
        user = UserProfile.objects.get(username='regularuser')
        assert self.client.login(username=user.email, password='password')
        AddonUser.objects.create(addon=self.app, user=user)
        doc = self.get_pq()
        eq_(doc('.button.product').length, 1)
        eq_(doc('.manage').length, 1)

    def test_free_install_button_for_app_reviewer(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(json.loads(doc('.mkt-tile').attr('data-product'))['recordUrl'],
            self.dev_receipt_url())
        eq_(doc('.button.product').length, 1)
        eq_(doc('.product.install').length, 1)
        eq_(doc('.manage').length, 0)

    def test_free_install_button_for_addon_reviewer(self):
        self.make_premium(self.app)
        GroupUser.objects.filter(group__name='App Reviewers').delete()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(json.loads(doc('.mkt-tile').attr('data-product'))['recordUrl'],
            urlparams(self.app.get_detail_url('record'), src='mkt-detail'))
        eq_(doc('.button.product').length, 1)
        eq_(doc('.product.install').length, 0)
        eq_(doc('.manage').length, 0)

    def test_paid_install_button_for_anon(self):
        # This purchase should not be faked.
        self.make_premium(self.app)
        doc = self.get_pq()
        eq_(doc('.product.premium.button').length, 1)

    def test_disabled_payments_notice(self):
        self.create_switch('disabled-payments')
        self.make_premium(self.app)
        doc = self.get_pq()
        eq_(doc('.no-payments.notification-box').length, 1)

    def dev_receipt_url(self):
        return urlparams(reverse('receipt.issue',
                                 args=[self.app.app_slug]), src='mkt-detail')

    def test_install_button_src(self):
        eq_(self.get_pq()('.mkt-tile').attr('data-src'), 'mkt-detail')
        eq_(self.get_pq(src='xxx')('.mkt-tile').attr('data-src'), 'xxx')

    def test_paid_install_button_for_owner(self):
        self.make_premium(self.app)
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(json.loads(doc('.mkt-tile').attr('data-product'))['recordUrl'],
            self.dev_receipt_url())
        eq_(doc('.product.install.premium').length, 1)
        eq_(doc('.manage').length, 1)

    def test_paid_install_button_for_dev(self):
        self.make_premium(self.app)
        user = UserProfile.objects.get(username='regularuser')
        assert self.client.login(username=user.email, password='password')
        AddonUser.objects.create(addon=self.app, user=user)
        doc = self.get_pq()
        eq_(json.loads(doc('.mkt-tile').attr('data-product'))['recordUrl'],
            self.dev_receipt_url())
        eq_(doc('.product.install.premium').length, 1)
        eq_(doc('.manage').length, 1)

    def test_paid_install_button_for_app_reviewer(self):
        self.make_premium(self.app)
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(json.loads(doc('.mkt-tile').attr('data-product'))['recordUrl'],
            self.dev_receipt_url())
        eq_(doc('button.product.premium').length, 1)
        eq_(doc('button.product.install.premium').length, 0)
        eq_(doc('.manage').length, 0)

    def test_paid_install_button_for_addon_reviewer(self):
        self.make_premium(self.app)
        GroupUser.objects.filter(group__name='App Reviewers').delete()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(json.loads(doc('.mkt-tile').attr('data-product'))['recordUrl'],
            urlparams(self.app.get_detail_url('record'), src='mkt-detail'))
        eq_(doc('button.product.premium').length, 1)
        eq_(doc('button.product.install.premium').length, 0)
        eq_(doc('.manage').length, 0)

    def test_tile_ratings_link(self):
        # Assert that we have the link to the ratings page in the header tile.
        self.create_switch(name='ratings')
        eq_(self.get_pq()('.mkt-tile .rating_link').attr('href'),
            self.app.get_ratings_url())

    def test_no_paid_public_install_button_for_reviewer(self):
        # Too bad. Reviewers can review the app from the Reviewer Tools.
        self.make_premium(self.app)
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(doc('.button.product.premium').length, 1)
        eq_(doc('.manage').length, 0)

    def test_no_paid_pending_install_button_for_reviewer(self):
        # Too bad. Reviewers can review the app from the Reviewer Tools.
        self.app.update(status=amo.STATUS_PENDING)
        self.make_premium(self.app)
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(doc('.button.product.premium').length, 1)
        eq_(doc('.manage').length, 0)

    def test_manage_button_for_admin(self):
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        eq_(self.get_pq()('.manage').length, 1)

    def test_manage_button_for_owner(self):
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        eq_(self.get_pq()('.manage').length, 1)

    def test_manage_button_for_dev(self):
        user = UserProfile.objects.get(username='regularuser')
        assert self.client.login(username=user.email, password='password')
        AddonUser.objects.create(addon=self.app, user=user)
        eq_(self.get_pq()('.manage').length, 1)

    def test_no_manage_button_for_nondev(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        eq_(self.get_pq()('.manage').length, 0)

    def test_no_manage_button_for_anon(self):
        eq_(self.get_pq()('.manage').length, 0)

    def test_review_history_button_for_reviewers(self):
        # Public apps get a "Review History" button.
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(doc('.button.reviewer').length, 1)
        eq_(doc('.button.reviewer').text(), 'Review History')

        # Pending apps get "Approve / Reject" button.
        self.app.update(status=amo.STATUS_PENDING)
        doc = self.get_pq()
        eq_(doc('.button.reviewer').length, 1)
        eq_(doc('.button.reviewer').text(), 'Approve / Reject')

    def test_upsell(self):
        eq_(self.get_pq()('#upsell').length, 0)
        premie = amo.tests.app_factory(manifest_url='http://omg.org/yes')
        AddonUpsell.objects.create(free=self.app, premium=premie)
        upsell = self.get_pq()('#upsell')
        eq_(upsell.length, 1)
        eq_(upsell.find('.name').text(), unicode(premie.name))
        eq_(upsell.find('.icon').attr('src'), premie.get_icon_url(32))

    def test_upsell_hidden(self):
        """Test that the upsell is hidden if it is not visible to the user."""
        eq_(self.get_pq()('#upsell').length, 0)
        premie = amo.tests.app_factory(manifest_url='http://omg.org/yes')
        AddonExcludedRegion.objects.create(addon=premie,
                                           region=mkt.regions.CA.id)
        AddonUpsell.objects.create(free=self.app, premium=premie)

        eq_(self.get_pq(region=mkt.regions.CA.slug)('#upsell').length, 0)
        eq_(self.get_pq(region=mkt.regions.US.slug)('#upsell').length, 1)

    def test_no_summary_no_description(self):
        self.app.summary = self.app.description = ''
        self.app.save()
        description = self.get_pq()('.blurbs')
        eq_(description.find('.summary').text(), '')

    def test_has_summary(self):
        self.app.summary = 'sumthang brief'
        self.app.description = ''
        self.app.save()
        description = self.get_pq()('.summary')
        eq_(description.text(), self.app.summary)

    def test_has_description(self):
        self.app.summary = ''
        self.app.description = 'a whole lotta text'
        self.app.save()
        description = self.get_pq()('.description')
        eq_(description.text(), self.app.description)

    def test_no_developer_comments(self):
        eq_(self.get_pq()('.developer-comments').length, 0)

    def test_has_developer_comments(self):
        self.app.developer_comments = 'hot ish is coming brah'
        self.app.save()
        eq_(self.get_pq()('.developer-comments').text(),
            self.app.developer_comments)

    def test_has_version(self):
        self.app.summary = ''
        self.app.description = ''
        vers = Version.objects.create(addon=self.app, version='1.0')
        self.app._current_version = vers
        self.app.is_packaged = True
        self.app.save()
        version = self.get_pq()('.package-version')
        eq_(version.text(),
            'Latest version: %s' % str(self.app.current_version))

    def test_no_support(self):
        eq_(self.get_pq()('.developer-comments').length, 0)

    def test_has_support_email(self):
        self.app.support_email = 'gkoberger@mozilla.com'
        self.app.save()
        email = self.get_pq()('.support .support-email')
        eq_(email.length, 1)
        eq_(email.remove('a').remove('span.i').text().replace(' ', ''),
            'moc.allizom@regrebokg', 'Email should be reversed')

    def test_has_support_url(self):
        self.app.support_url = 'http://omg.org/yes'
        self.app.save()
        url = self.get_pq()('.support .support-url')
        eq_(url.length, 1)
        eq_(url.find('a').attr('href'), external_url(self.app.support_url))

    def test_has_support_both(self):
        # I don't know what this was meant to test.
        raise SkipTest
        self.app.support_email = 'gkoberger@mozilla.com'
        self.app.support_url = 'http://omg.org/yes'
        self.app.save()
        li = self.get_pq()('.support .contact-support')
        eq_(li.find('.support-email').length, 1)
        eq_(li.find('.support-url').length, 1)

    def test_no_homepage(self):
        eq_(self.get_pq()('.support .homepage').length, 0)

    def test_has_homepage(self):
        self.app.homepage = 'http://omg.org/yes'
        self.app.save()
        url = self.get_pq()('.support .homepage')
        eq_(url.length, 1)
        eq_(url.find('a').attr('href'), external_url(self.app.homepage))

    def test_no_stats_without_waffle(self):
        # No stats on consumer pages for now.
        raise SkipTest
        # TODO: Remove this test when `app-stats` switch gets unleashed.
        self.app.update(public_stats=True)
        eq_(self.get_app().public_stats, True)
        eq_(self.get_pq()('.more-info .view-stats').length, 0)

    def test_no_public_stats(self):
        # No stats on consumer pages for now.
        raise SkipTest
        waffle.Switch.objects.create(name='app-stats', active=True)
        eq_(self.app.public_stats, False)
        eq_(self.get_pq()('.more-info .view-stats').length, 0)

    def test_public_stats(self):
        # No stats on consumer pages for now.
        raise SkipTest
        waffle.Switch.objects.create(name='app-stats', active=True)
        self.app.update(public_stats=True)
        eq_(self.get_app().public_stats, True)
        p = self.get_pq()('.more-info .view-stats')
        eq_(p.length, 1)
        eq_(p.find('a').attr('href'),
            reverse('mkt.stats.overview', args=[self.app.app_slug]))

    def test_free_no_preapproval(self):
        doc = self.get_pq()
        eq_(json.loads(doc('body').attr('data-user'))['pre_auth'], False)

    def test_free_preapproval_enabled(self):
        PreApprovalUser.objects.create(user=self.get_user(), paypal_key='xyz')
        doc = self.get_pq()
        eq_(json.loads(doc('body').attr('data-user'))['pre_auth'], False)

    def test_paid_no_preapproval_anonymous(self):
        self.make_premium(self.app)
        doc = self.get_pq()
        eq_(json.loads(doc('body').attr('data-user'))['pre_auth'], False)

    def test_paid_no_preapproval_authenticated(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.make_premium(self.app)
        doc = self.get_pq()
        eq_(json.loads(doc('body').attr('data-user'))['pre_auth'], False)

    def test_paid_preapproval_enabled(self):
        self.make_premium(self.app)
        user = self.get_user()
        assert self.client.login(username=user.email, password='password')
        PreApprovalUser.objects.create(user=user, paypal_key='xyz')
        doc = self.get_pq()
        eq_(json.loads(doc('body').attr('data-user'))['pre_auth'], True)


class TestDetailPagePermissions(DetailBase):

    def log_in_as(self, role):
        if role == 'owner':
            username = 'steamcube@mozilla.com'
        elif role == 'admin':
            username = 'admin@mozilla.com'
        else:
            assert NotImplementedError('Huh? Pick a real role.')
        assert self.client.login(username=username, password='password')

    def get_pq(self, **kw):
        data = kw.pop('data', {})
        if kw:
            self.app.update(**kw)
        r = self.client.get(self.url, data)
        eq_(r.status_code, 200)
        return pq(r.content)

    def get_msg(self, visible, **kw):
        doc = self.get_pq(**kw)

        status = doc('#product-status')
        eq_(status.length, 1)

        if visible:
            eq_(doc.find('.actions').length, 1,
                'The rest of the page should be visible')
        else:
            url = self.app.get_dev_url('versions')
            eq_(status.find('a[href="%s"]' % url).length,
                0, 'There should be no Manage Status link')
            eq_(doc.find('.actions').length, 0,
                'The rest of the page should be invisible')

        return status

    @mock.patch.object(settings, 'ENGAGE_ROBOTS', True)
    def test_no_engaged_robots_for_invisible(self):
        # Check that invisible (non-public) apps do not get indexed.
        for s in amo.WEBAPPS_UNLISTED_STATUSES:
            eq_(self.get_pq(status=s)('meta[content=noindex]').length, 1,
                'Expected a <meta> tag for status %r' %
                unicode(amo.STATUS_CHOICES[s]))

    @mock.patch.object(settings, 'ENGAGE_ROBOTS', True)
    def test_no_engaged_robots_for_disabled(self):
        # Check that disabled apps do not get indexed.
        self.app.update(disabled_by_user=True)
        eq_(self.get_pq()('meta[content=noindex]').length, 1)

    def test_public(self):
        doc = self.get_pq(status=amo.STATUS_PUBLIC)
        eq_(doc('#product-status').length, 0)
        eq_(doc('.summary').length, 1,
            'The rest of the page should be visible')

    def test_deleted(self):
        self.app.update(status=amo.STATUS_DELETED)
        r = self.client.get(self.url)
        eq_(r.status_code, 404)

    def test_incomplete(self):
        msg = self.get_msg(visible=False, status=amo.STATUS_NULL)
        txt = msg.text()
        assert 'incomplete' in txt, (
            'Expected something about it being incomplete: %s' % txt)
        eq_(msg.find('a').length, 0)

    def test_rejected(self):
        msg = self.get_msg(visible=False, status=amo.STATUS_REJECTED).text()
        assert 'rejected' in msg, (
            'Expected something about it being rejected: %s' % msg)

    def test_pending(self):
        msg = self.get_msg(visible=False, status=amo.STATUS_PENDING).text()
        assert 'awaiting review' in msg, (
            'Expected something about it being pending: %s' % msg)

    def test_public_waiting(self):
        msg = self.get_msg(visible=False, status=amo.STATUS_PUBLIC_WAITING)
        txt = msg.text()
        assert 'approved' in txt and 'unavailable' in txt, (
            'Expected something about it being approved and unavailable: %s' %
            txt)
        url = self.app.get_dev_url('versions')
        eq_(msg.find('a[href="%s"]' % url).length, 0,
            'There should be no Manage Status link')

    def test_disabled_by_mozilla(self):
        msg = self.get_msg(visible=False, status=amo.STATUS_DISABLED).text()
        assert 'disabled by Mozilla' in msg, (
            'Expected a rejection message: %s' % msg)

    def test_blocked_by_mozilla(self):
        msg = self.get_msg(visible=False, status=amo.STATUS_BLOCKED).text()
        assert 'blocked by Mozilla' in msg, (
            'Expected a rejection message: %s' % msg)

    def test_disabled_by_user(self):
        msg = self.get_msg(visible=False, disabled_by_user=True).text()
        assert 'disabled by its developer' in msg, (
            'Expected something about it being disabled: %s' % msg)

    def _test_dev_incomplete(self):
        # I'm a developer or admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_NULL)
        txt = msg.text()
        assert 'invisible' in txt, (
            'Expected something about it being incomplete: %s' % txt)
        eq_(msg.find('a').attr('href'), self.app.get_dev_url('versions'),
            'Expected a Manage Status link')

    def _test_dev_rejected(self):
        # I'm a developer or admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_REJECTED)
        txt = msg.text()
        assert 'invisible' in txt, (
            'Expected something about it being invisible: %s' % txt)
        eq_(msg.find('a').attr('href'), self.app.get_dev_url('versions'),
            'Expected a Manage Status link')

    def _test_dev_pending(self):
        # I'm a developer or an admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_PENDING)
        txt = msg.text()
        assert 'awaiting review' in txt, (
            'Expected something about it being pending: %s' % txt)
        eq_(msg.find('a').attr('href'), self.app.get_dev_url('versions'),
            'Expected a Manage Status link')

    def _test_dev_public_waiting(self):
        # I'm a developer or an admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_PUBLIC_WAITING)
        txt = msg.text()
        assert ' approved ' in txt and ' awaiting ' in txt, (
            'Expected something about it being approved and waiting: %s' % txt)
        eq_(msg.find('a').attr('href'), self.app.get_dev_url('versions'),
            'Expected a Manage Status link')

    def _test_dev_disabled_by_mozilla(self):
        # I'm a developer or an admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_DISABLED)
        txt = msg.text()
        assert 'disabled by Mozilla' in txt, (
            'Expected something about it being disabled: %s' % txt)
        assert msg.find('.emaillink').length, (
            'Expected an email link so I can yell at Mozilla')

    def _test_dev_blocked_by_mozilla(self):
        # I'm a developer or an admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_BLOCKED)
        txt = msg.text()
        assert 'blocked by Mozilla' in txt, (
            'Expected something about it being blocked: %s' % txt)
        assert msg.find('.emaillink').length, (
            'Expected an email link so I can yell at Mozilla')

    def _test_dev_disabled_by_user(self):
        # I'm a developer or an admin.
        msg = self.get_msg(visible=True, disabled_by_user=True)
        txt = msg.text()
        assert 'invisible' in txt, (
            'Expected something about it being invisible: %s' % txt)
        eq_(msg.find('a').attr('href'), self.app.get_dev_url('versions'),
            'Expected a Manage Status link')

    def test_owner_incomplete(self):
        self.log_in_as('owner')
        self._test_dev_incomplete()

    def test_owner_rejected(self):
        self.log_in_as('owner')
        self._test_dev_rejected()

    def test_owner_pending(self):
        self.log_in_as('owner')
        self._test_dev_pending()

    def test_owner_public_waiting(self):
        self.log_in_as('owner')
        self._test_dev_public_waiting()

    def test_owner_disabled_by_mozilla(self):
        self.log_in_as('owner')
        self._test_dev_disabled_by_mozilla()

    def test_owner_blocked_by_mozilla(self):
        self.log_in_as('owner')
        self._test_dev_blocked_by_mozilla()

    def test_owner_disabled_by_user(self):
        self.log_in_as('owner')
        self._test_dev_disabled_by_user()

    def test_admin_incomplete(self):
        self.log_in_as('admin')
        self._test_dev_incomplete()

    def test_admin_rejected(self):
        self.log_in_as('admin')
        self._test_dev_rejected()

    def test_admin_pending(self):
        self.log_in_as('admin')
        self._test_dev_pending()

    def test_admin_public_waiting(self):
        self.log_in_as('admin')
        self._test_dev_public_waiting()

    def test_admin_disabled_by_mozilla(self):
        self.log_in_as('admin')
        self._test_dev_disabled_by_mozilla()

    def test_admin_blocked_by_mozilla(self):
        self.log_in_as('admin')
        self._test_dev_blocked_by_mozilla()

    def test_admin_disabled_by_user(self):
        self.log_in_as('admin')
        self._test_dev_disabled_by_user()

    def test_unrated_pending_brazil_game(self):
        # If I'm a regular user, I should never see the
        # "apply for a rating" text.

        self.make_game()
        self.app.update(status=amo.STATUS_PENDING)

        for region in mkt.regions.REGIONS_DICT:
            doc = self.get_pq(data={'region': region})
            disclaimer = doc('#product-rating-status')

            if region == mkt.regions.BR.slug:
                # Unrated games should be blocked in only Brazil.
                eq_(disclaimer.length, 1)
                txt = disclaimer.text()
                assert (' unavailable in your region ' in txt and
                        'Brazil' in txt), ('Expected message about '
                                           'invisible in Brazil: %s' % txt)
            else:
                eq_(disclaimer.length, 0)

            eq_(doc('.button.product').length, 0)
            eq_(doc('.content-ratings').length, 0)

    def test_unrated_public_brazil_game(self):
        # If I'm a regular user, I should see the
        # "not available in your region" text.

        self.make_game()

        for region in mkt.regions.REGIONS_DICT:
            doc = self.get_pq(data={'region': region})
            disclaimer = doc('#product-rating-status')

            if region == mkt.regions.BR.slug:
                # Unrated games should be blocked in only Brazil.
                eq_(disclaimer.length, 1)
                txt = disclaimer.text()
                assert (' unavailable in your region ' in txt and
                        'Brazil' in txt), ('Expected message about '
                                           'invisible in Brazil: %s' % txt)
                eq_(doc('.button.product').length, 0)
            else:
                eq_(disclaimer.length, 0)
                eq_(doc('.button.product').length, 1)

            eq_(doc('.content-ratings').length, 0)

    def test_unrated_brazil_game_apply_message_for_owner_or_admin(self):
        # If I'm an owner or admin, I should always see the
        # "apply for a rating" text. Even outside of the Brazil store.

        self.make_game()

        for status in (amo.STATUS_PENDING,
                       amo.STATUS_DISABLED,
                       amo.STATUS_PUBLIC):
            self.app.update(status=status)

            for user in ('owner', 'admin'):
                self.log_in_as(user)

                for region in mkt.regions.REGIONS_DICT:
                    doc = self.get_pq(data={'region': region})
                    disclaimer = doc('#product-rating-status')

                    eq_(disclaimer.length, 1,
                        'Missing disclaimer in %r for %r when %r'
                        % (region, user, status))

                    txt = disclaimer.text()
                    assert ' unavailable for users in Brazil' in txt, (
                        u'Expected to say it is invisible in Brazil: %s' % txt)

                    eq_(doc('.button.product').length, 1)
                    eq_(doc('.content-ratings').length, 0)

    def test_rated_pending_brazil_game_message_for_user(self):
        # If I'm a regular user, I should the "pending" text and I should
        # not see ratings for a pending, rated game.

        self.make_game(rated=True)
        self.app.update(status=amo.STATUS_PENDING)

        for region in mkt.regions.REGIONS_DICT:
            doc = self.get_pq(data={'region': region})
            eq_(doc('#product-rating-status').length, 0,
                'Unrated notice should not be shown')
            eq_(doc('#product-status').length, 1,
                'Pending notice should be shown')
            eq_(doc('.button.product').length, 0,
                'Install button should never be exposed for pending app')
            eq_(doc('.content-ratings').length, 0,
                'Ratings should never be exposed for pending app')

    def test_rated_public_brazil_game_ratings(self):
        # If I'm anyone, I should should see ratings for a public,
        # rated game but only in Brazil.

        self.make_game(rated=True)

        for region in mkt.regions.REGIONS_DICT:
            doc = self.get_pq(data={'region': region})
            eq_(doc('#product-rating-status').length, 0,
                'Unrated notice should not be shown for rated app')
            eq_(doc('.button.product').length, 1,
                'Install button should be exposed for rated app')

            ratings = doc('.content-ratings')
            if region == mkt.regions.BR.slug:
                eq_(ratings.length, 1)

                ratings = ratings.find('.content-rating')
                eq_(ratings.length, 2)

                # First content rating (ORDER BY vileness ASC).
                first = ratings.eq(0)
                cr = mkt.ratingsbodies.DJCTQ_L
                eq_(first.find('.icon-L').text(), cr.name)
                eq_(first.find('.description').text(), cr.description)

                # Second content rating.
                second = ratings.eq(1)
                cr = mkt.ratingsbodies.DJCTQ_18
                eq_(second.find('.icon-18').text(), cr.name)
                eq_(second.find('.description').text(), cr.description)
            else:
                eq_(doc('.content-ratings').length, 0,
                    'Should see ratings in Brazil only')


class TestPrivacy(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.app = Webapp.objects.get(id=337141)
        self.url = self.app.get_detail_url('privacy')

    def test_app_statuses(self):
        eq_(self.app.status, amo.STATUS_PUBLIC)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

        # Incomplete or pending apps should 404.
        for status in (amo.STATUS_NULL, amo.STATUS_PENDING):
            self.app.update(status=status)
            r = self.client.get(self.url)
            eq_(r.status_code, 404)

        # Public-yet-disabled apps should 404.
        self.app.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        eq_(self.client.get(self.url).status_code, 404)

    def test_policy(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.policy-statement').text(),
            strip_tags(get_clean(self.app.privacy_policy)))

    def test_policy_html(self):
        self.app.privacy_policy = """
            <strong> what the koberger..</strong>
            <ul>
                <li>papparapara</li>
                <li>todotodotodo</li>
            </ul>
            <ol>
                <a href="irc://irc.mozilla.org/firefox">firefox</a>

                Introduce yourself to the community, if you like!
                This text will appear publicly on your user info page.
                <li>papparapara2</li>
                <li>todotodotodo2</li>
            </ol>
            """
        self.app.save()
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        doc = pq(r.content)('.policy-statement')
        eq_(get_clean(doc('strong')), '<strong> what the koberger..</strong>')
        eq_(get_clean(doc('ul')),
            '<ul><li>papparapara</li> <li>todotodotodo</li> </ul>')
        eq_(get_clean(doc('ol a').text()), 'firefox')
        eq_(get_clean(doc('ol li:first')), '<li>papparapara2</li>')


@mock.patch.object(settings, 'RECAPTCHA_PRIVATE_KEY', 'something')
class TestReportAbuse(DetailBase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        super(TestReportAbuse, self).setUp()
        self.url = self.app.get_detail_url('abuse')

        patcher = mock.patch.object(settings, 'TASK_USER_ID', 4043307)
        patcher.start()
        self.addCleanup(patcher.stop)

    def log_in(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def test_recaptcha_shown_for_anonymous(self):
        eq_(self.get_pq()('#recap-container').length, 1)

    def test_no_recaptcha_for_authenticated(self):
        self.log_in()
        eq_(self.get_pq()('#recap-container').length, 0)

    @mock.patch('captcha.fields.ReCaptchaField.clean', new=mock.Mock)
    def test_abuse_anonymous(self):
        self.client.post(self.url, {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(addon=337141)
        eq_(report.message, 'spammy')
        eq_(report.reporter, None)

    def test_abuse_anonymous_fails(self):
        r = self.client.post(self.url, {'text': 'spammy'})
        assert 'recaptcha' in r.context['abuse_form'].errors

    def test_abuse_authenticated(self):
        self.log_in()
        self.client.post(self.url, {'text': 'spammy'})
        eq_(len(mail.outbox), 1)
        assert 'spammy' in mail.outbox[0].body
        report = AbuseReport.objects.get(addon=337141)
        eq_(report.message, 'spammy')
        eq_(report.reporter.email, 'regular@mozilla.com')

    def test_abuse_name(self):
        self.app.name = 'Bmrk.ru Социальные закладки'
        self.app.save()
        self.log_in()
        self.client.post(self.url, {'text': 'spammy'})
        assert 'spammy' in mail.outbox[0].body
        assert AbuseReport.objects.get(addon=self.app)


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
        amo.log(amo.LOG.CREATE_ADDON, self.app, user=self.user)
        amo.log(amo.LOG.ADMIN_USER_EDITED, self.user, 'spite', user=self.user)
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        doc = pq(res.content)
        assert 'created' in doc('li.item').eq(0).text()
        assert 'edited' in doc('li.item').eq(1).text()


class TestPackagedManifest(DetailBase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(is_packaged=True)
        # Create a fake package to go along with the app.
        latest_file = self.app.get_latest_file()
        with storage.open(latest_file.file_path,
                          mode='w') as package:
            test_package = zipfile.ZipFile(package, 'w')
            test_package.writestr('manifest.webapp', 'foobar')
            test_package.close()
            latest_file.update(hash=latest_file.generate_hash())

        self.url = self.app.get_detail_url('manifest')

    def tearDown(self):
        storage.delete(self.app.get_latest_file().file_path)

    def get_digest_from_manifest(self, manifest=None):
        if manifest is None:
            manifest = self._mocked_json()
        elif not isinstance(manifest, (str, unicode)):
            manifest = json.dumps(manifest)

        hash_ = hashlib.md5()
        hash_.update(manifest)
        hash_.update(self.app.get_latest_file().hash)
        return hash_.hexdigest()

    def _mocked_json(self):
        data = {
            u'name': u'Packaged App √',
            u'version': u'1.0',
            u'size': 123456,
            u'release_notes': u'Bug fixes',
            u'packaged_path': u'/path/to/file.zip',
        }
        return json.dumps(data)

    def login_as_reviewer(self):
        self.client.logout()
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')

    def login_as_author(self):
        self.client.logout()
        user = UserProfile.objects.get(username='regularuser')
        AddonUser.objects.create(addon=self.app, user=user)
        assert self.client.login(username=user.email, password='password')

    def test_non_packaged(self):
        self.app.update(is_packaged=False)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    def test_disabled_by_user(self):
        self.app.update(disabled_by_user=True)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    @mock.patch('mkt.webapps.models.Webapp.get_cached_manifest')
    def test_app_public(self, _mock):
        _mock.return_value = self._mocked_json()
        res = self.client.get(self.url)
        eq_(res.content, self._mocked_json())
        eq_(res['Content-Type'], 'application/x-web-app-manifest+json')
        eq_(res['ETag'], self.get_digest_from_manifest())

    @mock.patch('mkt.webapps.models.Webapp.get_cached_manifest')
    def test_app_public(self, _mock):
        _mock.return_value = self._mocked_json()

        # Get the minifest with the first simulated package.
        res = self.client.get(self.url)
        eq_(res.content, self._mocked_json())
        eq_(res['Content-Type'], 'application/x-web-app-manifest+json')

        first_etag = res['ETag']

        # Write a new value to the packaged app.
        latest_file = self.app.get_latest_file()
        with storage.open(latest_file.file_path,
                          mode='w') as package:
            test_package = zipfile.ZipFile(package, 'w')
            test_package.writestr('manifest.webapp', 'poop')
            test_package.close()
            latest_file.update(hash=latest_file.generate_hash())

        # Get the minifest with the second simulated package.
        res = self.client.get(self.url)
        eq_(res.content, self._mocked_json())
        eq_(res['Content-Type'], 'application/x-web-app-manifest+json')

        second_etag = res['ETag']

        self.assertNotEqual(first_etag, second_etag)

    @mock.patch('mkt.webapps.models.Webapp.get_cached_manifest')
    def test_conditional_get(self, _mock):
        _mock.return_value = self._mocked_json()
        etag = self.get_digest_from_manifest()
        self.client.defaults['HTTP_IF_NONE_MATCH'] = '"%s"' % etag
        res = self.client.get(self.url)
        eq_(res.content, '')
        eq_(res.status_code, 304)

    def test_app_pending(self):
        self.app.update(status=amo.STATUS_PENDING)
        res = self.client.get(self.url)
        eq_(res.status_code, 404)

    @mock.patch('mkt.webapps.models.Webapp.get_cached_manifest')
    def test_app_pending_reviewer(self, _mock):
        self.login_as_reviewer()
        self.app.update(status=amo.STATUS_PENDING)
        _mock.return_value = self._mocked_json()
        res = self.client.get(self.url)
        eq_(res.content, self._mocked_json())
        eq_(res['Content-Type'], 'application/x-web-app-manifest+json')
        eq_(res['ETag'], self.get_digest_from_manifest())

    @mock.patch('mkt.webapps.models.Webapp.get_cached_manifest')
    def test_app_pending_author(self, _mock):
        self.login_as_author()
        self.app.update(status=amo.STATUS_PENDING)
        _mock.return_value = self._mocked_json()
        res = self.client.get(self.url)
        eq_(res.content, self._mocked_json())
        eq_(res['Content-Type'], 'application/x-web-app-manifest+json')
        eq_(res['ETag'], self.get_digest_from_manifest())

    @mock.patch.object(settings, 'SITE_URL', 'http://hy.fr')
    def test_blocked_app(self):
        self.app.update(status=amo.STATUS_BLOCKED)
        blocked_path = 'packaged-apps/blocklisted.zip'
        res = self.client.get(self.url)
        eq_(res['Content-type'], 'application/x-web-app-manifest+json')
        assert 'etag' in res._headers
        data = json.loads(res.content)
        eq_(data['name'], self.app.name)
        eq_(data['size'],
            os.stat(os.path.join(settings.MEDIA_ROOT, blocked_path)).st_size)
        eq_(data['package_path'],
            os.path.join(settings.SITE_URL, 'media', blocked_path))
        assert data['release_notes'].startswith(u'This app has been blocked')

    @mock.patch.object(settings, 'MIDDLEWARE_CLASSES',
        settings.MIDDLEWARE_CLASSES + type(settings.MIDDLEWARE_CLASSES)([
            'amo.middleware.NoConsumerMiddleware',
            'amo.middleware.LoginRequiredMiddleware'
        ])
    )
    @mock.patch('mkt.webapps.models.Webapp.get_cached_manifest')
    def test_logged_out(self, _mock):
        _mock.return_value = self._mocked_json()
        self.client.logout()
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(res['Content-type'], 'application/x-web-app-manifest+json')
