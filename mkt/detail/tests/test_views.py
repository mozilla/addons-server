# -*- coding: utf-8 -*-
import json

from django.conf import settings
from django.core import mail
from django.utils.html import strip_tags

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq
from tower import strip_whitespace
import waffle

from abuse.models import AbuseReport
import amo
from amo.helpers import external_url, numberfmt, urlparams
import amo.tests
from amo.urlresolvers import reverse
from addons.models import AddonCategory, AddonUpsell, AddonUser, Category
from market.models import PreApprovalUser
from users.models import UserProfile

from mkt.webapps.models import Webapp


def get_clean(selection):
    return strip_whitespace(str(selection))


class DetailBase(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_detail_url()

    def get_webapp(self):
        return Webapp.objects.get(id=337141)

    def get_user(self):
        return UserProfile.objects.get(email='regular@mozilla.com')

    def get_pq(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        return pq(r.content)


class TestDetail(DetailBase):

    def test_page(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_categories(self):
        cat = Category.objects.create(name='Lifestyle', slug='lifestyle',
                                      type=amo.ADDON_WEBAPP)
        AddonCategory.objects.create(addon=self.webapp, category=cat)
        links = self.get_pq()('.cats a')
        eq_(links.length, 1)
        eq_(links.attr('href'), cat.get_url_path())
        eq_(links.text(), cat.name)

    def test_free_install_button_for_anon(self):
        doc = self.get_pq()
        eq_(doc('.product').length, 1)
        eq_(doc('.faked-purchase').length, 0)

    def test_free_install_button_for_owner(self):
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(doc('.product').length, 1)
        eq_(doc('.faked-purchase').length, 0)
        eq_(doc('.manage').length, 1)

    def test_free_install_button_for_dev(self):
        user = UserProfile.objects.get(username='regularuser')
        assert self.client.login(username=user.email, password='password')
        AddonUser.objects.create(addon=self.webapp, user=user)
        doc = self.get_pq()
        eq_(doc('.product').length, 1)
        eq_(doc('.faked-purchase').length, 0)
        eq_(doc('.manage').length, 1)

    def test_free_install_button_for_reviewer(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(doc('.product').length, 1)
        eq_(doc('.faked-purchase').length, 0)
        eq_(doc('.manage').length, 0)

    def test_paid_install_button_for_anon(self):
        # This purchase should not be faked.
        self.make_premium(self.webapp)
        doc = self.get_pq()
        eq_(doc('.product.premium').length, 1)
        eq_(doc('.faked-purchase').length, 0)

    def dev_receipt_url(self):
        return urlparams(reverse('receipt.issue',
                                 args=[self.webapp.app_slug]), src='')

    def test_paid_install_button_for_owner(self):
        self.make_premium(self.webapp)
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(json.loads(doc('a.install').attr('data-product'))['recordUrl'],
            self.dev_receipt_url())
        eq_(doc('.product.install.premium').length, 1)
        eq_(doc('.faked-purchase').length, 1)
        eq_(doc('.manage').length, 1)

    def test_paid_install_button_for_dev(self):
        self.make_premium(self.webapp)
        user = UserProfile.objects.get(username='regularuser')
        assert self.client.login(username=user.email, password='password')
        AddonUser.objects.create(addon=self.webapp, user=user)
        doc = self.get_pq()
        eq_(json.loads(doc('a.install').attr('data-product'))['recordUrl'],
            self.dev_receipt_url())
        eq_(doc('.product.install.premium').length, 1)
        eq_(doc('.faked-purchase').length, 1)
        eq_(doc('.manage').length, 1)

    def test_no_paid_public_install_button_for_reviewer(self):
        # Too bad. Reviewers can review the app from the Reviewer Tools.
        self.make_premium(self.webapp)
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(doc('.product.premium').length, 1)
        eq_(doc('.faked-purchase').length, 0)
        eq_(doc('.manage').length, 0)

    def test_no_paid_pending_install_button_for_reviewer(self):
        # Too bad. Reviewers can review the app from the Reviewer Tools.
        self.webapp.update(status=amo.STATUS_PENDING)
        self.make_premium(self.webapp)
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        doc = self.get_pq()
        eq_(doc('.product.premium').length, 1)
        eq_(doc('.faked-purchase').length, 0)
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
        AddonUser.objects.create(addon=self.webapp, user=user)
        eq_(self.get_pq()('.manage').length, 1)

    def test_no_manage_button_for_nondev(self):
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        eq_(self.get_pq()('.manage').length, 0)

    def test_no_manage_button_for_anon(self):
        eq_(self.get_pq()('.manage').length, 0)

    def test_upsell(self):
        eq_(self.get_pq()('#upsell.wide').length, 0)
        premie = amo.tests.app_factory(manifest_url='http://omg.org/yes')
        AddonUpsell.objects.create(free=self.webapp, premium=premie,
                                   text='XXX')
        upsell = self.get_pq()('#upsell.wide')
        eq_(upsell.length, 1)
        eq_(upsell.find('.upsell').find('.name').text(), unicode(premie.name))
        eq_(upsell.find('.icon').attr('src'), premie.get_icon_url(64))
        eq_(upsell.find('.special').attr('href'),
            premie.get_url_path() + '?src=mkt-detail-upsell')
        eq_(upsell.find('.price').text(), premie.get_price())
        eq_(upsell.find('.downloads').text().split(' ')[0],
            numberfmt(premie.weekly_downloads))
        eq_(upsell.find('.prose').text(), 'XXX')

    def test_no_summary_no_description(self):
        self.webapp.summary = self.webapp.description = ''
        self.webapp.save()
        description = self.get_pq()('.description')
        eq_(description.find('.summary').text(), '')
        eq_(description.find('.more').length, 0)

    def test_has_summary(self):
        self.webapp.summary = 'sumthang brief'
        self.webapp.description = ''
        self.webapp.save()
        description = self.get_pq()('.description')
        eq_(description.find('.summary').text(), self.webapp.summary)
        eq_(description.find('.more').length, 0)

    def test_has_description(self):
        self.webapp.summary = ''
        self.webapp.description = 'a whole lotta text'
        self.webapp.save()
        description = self.get_pq()('.description')
        eq_(description.find('.summary').remove('.collapse').text(), '')
        eq_(description.find('.more').text(), self.webapp.description)

    def test_no_developer_comments(self):
        eq_(self.get_pq()('.developer-comments').length, 0)

    def test_has_developer_comments(self):
        self.webapp.developer_comments = 'hot ish is coming brah'
        self.webapp.save()
        eq_(self.get_pq()('.developer-comments').text(),
            self.webapp.developer_comments)

    def test_no_support(self):
        eq_(self.get_pq()('.developer-comments').length, 0)

    def test_has_support_email(self):
        self.webapp.support_email = 'gkoberger@mozilla.com'
        self.webapp.save()
        email = self.get_pq()('.support .wide .support-email')
        eq_(email.length, 1)
        eq_(email.remove('a').remove('span.i').text().replace(' ', ''),
            'moc.allizom@regrebokg', 'Email should be reversed')

    def test_has_support_url(self):
        self.webapp.support_url = 'http://omg.org/yes'
        self.webapp.save()
        url = self.get_pq()('.support .wide .support-url')
        eq_(url.length, 1)
        eq_(url.find('a').attr('href'), external_url(self.webapp.support_url))

    def test_has_support_both(self):
        self.webapp.support_email = 'gkoberger@mozilla.com'
        self.webapp.support_url = 'http://omg.org/yes'
        self.webapp.save()
        li = self.get_pq()('.support .wide .contact-support')
        eq_(li.find('.support-email').length, 1)
        eq_(li.find('.support-url').length, 1)

    def test_no_homepage(self):
        eq_(self.get_pq()('.support .homepage').length, 0)

    def test_has_homepage(self):
        self.webapp.homepage = 'http://omg.org/yes'
        self.webapp.save()
        url = self.get_pq()('.support .wide .homepage')
        eq_(url.length, 1)
        eq_(url.find('a').text(), self.webapp.homepage)
        eq_(url.find('a').attr('href'), external_url(self.webapp.homepage))

    def test_no_stats_without_waffle(self):
        # TODO: Remove this test when `app-stats` switch gets unleashed.
        self.webapp.update(public_stats=True)
        eq_(self.get_webapp().public_stats, True)
        eq_(self.get_pq()('.more-info .view-stats').length, 0)

    def test_no_public_stats(self):
        waffle.Switch.objects.create(name='app-stats', active=True)
        eq_(self.webapp.public_stats, False)
        eq_(self.get_pq()('.more-info .view-stats').length, 0)

    def test_public_stats(self):
        waffle.Switch.objects.create(name='app-stats', active=True)
        self.webapp.update(public_stats=True)
        eq_(self.get_webapp().public_stats, True)
        p = self.get_pq()('.more-info .view-stats')
        eq_(p.length, 1)
        eq_(p.find('a').attr('href'),
            reverse('mkt.stats.overview', args=[self.webapp.app_slug]))

    def test_free_no_preapproval(self):
        eq_(self.get_pq()('.approval-pitch, .approval.checkmark').length, 0)

    def test_free_preapproval_enabled(self):
        PreApprovalUser.objects.create(user=self.get_user(), paypal_key='xyz')
        eq_(self.get_pq()('.approval-pitch, .approval.checkmark').length, 0)

    def test_paid_no_preapproval_anonymous(self):
        self.make_premium(self.webapp)
        doc = self.get_pq()
        eq_(doc('.approval-pitch').length, 0)
        eq_(doc('.approval.checkmark').length, 0)

    def test_paid_no_preapproval_authenticated(self):
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        self.make_premium(self.webapp)
        doc = self.get_pq()
        eq_(doc('.approval-pitch').length, 0)
        eq_(doc('.approval.checkmark').length, 0)

    def test_paid_preapproval_enabled(self):
        self.make_premium(self.webapp)
        user = self.get_user()
        assert self.client.login(username=user.email, password='password')
        PreApprovalUser.objects.create(user=user, paypal_key='xyz')
        doc = self.get_pq()
        eq_(doc('.approval-pitch').length, 0)
        eq_(doc('.approval.checkmark').length, 1)


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
        self.webapp.update(**kw)
        r = self.client.get(self.url)
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
            url = self.webapp.get_dev_url('versions')
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
        self.webapp.update(disabled_by_user=True)
        eq_(self.get_pq()('meta[content=noindex]').length, 1)

    def test_public(self):
        doc = self.get_pq(status=amo.STATUS_PUBLIC)
        eq_(doc('#product-status').length, 0)
        eq_(doc('.actions').length, 1, 'The rest of the page should visible')

    def test_deleted(self):
        self.webapp.update(status=amo.STATUS_DELETED)
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
        url = self.webapp.get_dev_url('versions')
        eq_(msg.find('a[href="%s"]' % url).length, 0,
            'There should be no Manage Status link')

    def test_disabled_by_mozilla(self):
        msg = self.get_msg(visible=False, status=amo.STATUS_DISABLED).text()
        assert 'disabled by Mozilla' in msg, (
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
        eq_(msg.find('a').attr('href'), self.webapp.get_dev_url('versions'),
            'Expected a Manage Status link')

    def _test_dev_rejected(self):
        # I'm a developer or admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_REJECTED)
        txt = msg.text()
        assert 'invisible' in txt, (
            'Expected something about it being invisible: %s' % txt)
        eq_(msg.find('a').attr('href'), self.webapp.get_dev_url('versions'),
            'Expected a Manage Status link')

    def _test_dev_pending(self):
        # I'm a developer or an admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_PENDING)
        txt = msg.text()
        assert 'awaiting review' in txt, (
            'Expected something about it being pending: %s' % txt)
        eq_(msg.find('a').attr('href'), self.webapp.get_dev_url('versions'),
            'Expected a Manage Status link')

    def _test_dev_public_waiting(self):
        # I'm a developer or an admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_PUBLIC_WAITING)
        txt = msg.text()
        assert ' approved ' and ' awaiting ' in txt, (
            'Expected something about it being approved and waiting: %s' % txt)
        eq_(msg.find('a').attr('href'), self.webapp.get_dev_url('versions'),
            'Expected a Manage Status link')

    def _test_dev_disabled_by_mozilla(self):
        # I'm a developer or an admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_DISABLED)
        txt = msg.text()
        assert 'disabled by Mozilla' in txt, (
            'Expected something about it being disabled: %s' % txt)
        assert msg.find('.emaillink').length, (
            'Expected an email link so I can yell at Mozilla')

    def _test_dev_disabled_by_user(self):
        # I'm a developer or an admin.
        msg = self.get_msg(visible=True, disabled_by_user=True)
        txt = msg.text()
        assert 'invisible' in txt, (
            'Expected something about it being invisible: %s' % txt)
        eq_(msg.find('a').attr('href'), self.webapp.get_dev_url('versions'),
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

    def test_admin_disabled_by_user(self):
        self.log_in_as('admin')
        self._test_dev_disabled_by_user()


class TestPrivacy(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Webapp.objects.get(id=337141)
        self.url = self.webapp.get_detail_url('privacy')

    def test_app_statuses(self):
        eq_(self.webapp.status, amo.STATUS_PUBLIC)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

        # Incomplete or pending apps should 404.
        for status in (amo.STATUS_NULL, amo.STATUS_PENDING):
            self.webapp.update(status=status)
            r = self.client.get(self.url)
            eq_(r.status_code, 404)

        # Public-yet-disabled apps should 404.
        self.webapp.update(status=amo.STATUS_PUBLIC, disabled_by_user=True)
        eq_(self.client.get(self.url).status_code, 404)

    def test_policy(self):
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('.policy-statement').text(),
            strip_tags(get_clean(self.webapp.privacy_policy)))

    def test_policy_html(self):
        self.webapp.privacy_policy = """
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
        self.webapp.save()
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
        self.url = self.webapp.get_detail_url('abuse')

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
        self.webapp.name = 'Bmrk.ru Социальные закладки'
        self.webapp.save()
        self.log_in()
        self.client.post(self.url, {'text': 'spammy'})
        assert 'spammy' in mail.outbox[0].body
        assert AbuseReport.objects.get(addon=self.webapp)
