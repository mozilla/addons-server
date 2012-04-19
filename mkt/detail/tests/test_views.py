import json

from django.conf import settings
from django.utils.html import strip_tags

import mock
from nose.plugins.skip import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
from tower import strip_whitespace

import amo
from amo.helpers import external_url
import amo.tests
from addons.models import AddonCategory, AddonUpsell, AddonUser, Category
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
        links = self.get_pq()('.categories a')
        eq_(links.length, 1)
        eq_(links.attr('href'), cat.get_url_path())
        eq_(links.text(), cat.name)

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
        eq_(self.get_pq()('#upsell').length, 0)
        premie = amo.tests.app_factory(manifest_url='http://omg.org/yes')
        AddonUpsell.objects.create(free=self.webapp, premium=premie,
                                   text='XXX')
        upsell = self.get_pq()('#upsell')
        eq_(upsell.length, 1)
        eq_(upsell.find('.upsell').text(), unicode(premie.name))
        eq_(upsell.find('.icon').attr('src'), premie.get_icon_url(16))
        eq_(upsell.find('.install').attr('data-manifesturl'),
            premie.manifest_url)
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
        eq_(description.find('.summary').text(), '')
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
        email = self.get_pq()('.support .support-email')
        eq_(email.length, 1)
        eq_(email.remove('a').remove('span.i').text().replace(' ', ''),
            'moc.allizom@regrebokg', 'Email should be reversed')

    def test_has_support_url(self):
        self.webapp.support_url = 'http://omg.org/yes'
        self.webapp.save()
        url = self.get_pq()('.support .support-url')
        eq_(url.length, 1)
        eq_(url.find('a').attr('href'), external_url(self.webapp.support_url))

    def test_has_support_both(self):
        self.webapp.support_email = 'gkoberger@mozilla.com'
        self.webapp.support_url = 'http://omg.org/yes'
        self.webapp.save()
        li = self.get_pq()('.support .contact-support')
        eq_(li.find('.support-email').length, 1)
        eq_(li.find('.support-url').length, 1)

    def test_no_homepage(self):
        eq_(self.get_pq()('.support .homepage').length, 0)

    def test_has_homepage(self):
        self.webapp.homepage = 'http://omg.org/yes'
        self.webapp.save()
        url = self.get_pq()('.support .homepage')
        eq_(url.length, 1)
        eq_(url.find('a').text(), self.webapp.homepage)
        eq_(url.find('a').attr('href'), external_url(self.webapp.homepage))


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
        msg = self.get_msg(visible=False, status=amo.STATUS_NULL).text()
        assert 'incomplete' in msg, (
            'Expected something about it being incomplete: %s' % msg)

    def test_rejected(self):
        msg = self.get_msg(visible=False, status=amo.STATUS_REJECTED).text()
        assert 'rejected' in msg, (
            'Expected something about it being rejected: %s' % msg)

    def test_pending(self):
        msg = self.get_msg(visible=False, status=amo.STATUS_PENDING).text()
        assert 'awaiting review' in msg, (
            'Expected something about it being pending: %s' % msg)

    def test_disabled_by_mozilla(self):
        msg = self.get_msg(visible=False, status=amo.STATUS_DISABLED).text()
        assert 'disabled by Mozilla' in msg, (
            'Expected a rejection message: %s' % msg)

    def test_disabled_by_user(self):
        msg = self.get_msg(visible=False, disabled_by_user=True).text()
        assert 'disabled by its developer' in msg, (
            'Expected something about it being disabled: %s' % msg)

    def _test_dev_rejected(self):
        # I'm a developer or admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_REJECTED)
        txt = msg.text()
        assert 'rejected' in txt, (
            'Expected something about it being rejected: %s' % txt)
        eq_(msg.find('a').attr('href'), self.webapp.get_dev_url('versions'),
            'Expected a Manage Status link')

    def _test_dev_pending(self):
        # I'm a developer or an admin.
        msg = self.get_msg(visible=True, status=amo.STATUS_PENDING)
        txt = msg.text()
        assert 'awaiting review' in txt, (
            'Expected something about it being pending: %s' % txt)
        url = self.webapp.get_dev_url('versions')
        eq_(msg.find('a[href="%s"]' % url).length, 0,
            'There should be no Manage Status link')

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
        assert 'disabled by its developer' in txt, (
            'Expected something about it being disabled: %s' % txt)
        eq_(msg.find('a').attr('href'), self.webapp.get_dev_url('versions'),
            'Expected a Manage Status link')

    def test_owner_rejected(self):
        self.log_in_as('owner')
        self._test_dev_rejected()

    def test_owner_pending(self):
        self.log_in_as('owner')
        self._test_dev_pending()

    def test_owner_disabled_by_mozilla(self):
        self.log_in_as('owner')
        self._test_dev_disabled_by_mozilla()

    def test_owner_disabled_by_user(self):
        self.log_in_as('owner')
        self._test_dev_disabled_by_user()

    def test_admin_rejected(self):
        self.log_in_as('admin')
        self._test_dev_rejected()

    def test_admin_pending(self):
        self.log_in_as('admin')
        self._test_dev_pending()

    def test_admin_disabled_by_mozilla(self):
        self.log_in_as('admin')
        self._test_dev_disabled_by_mozilla()

    def test_admin_disabled_by_user(self):
        self.log_in_as('admin')
        self._test_dev_disabled_by_user()


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestInstall(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.addon = amo.tests.app_factory(manifest_url='http://cbc.ca/man')
        self.url = self.addon.get_detail_url('record')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        assert self.client.login(username=self.user.email, password='password')

    def test_not_record_addon(self):
        self.addon.update(type=amo.ADDON_EXTENSION)
        self.client.post(self.url)
        eq_(self.user.installed_set.count(), 0)

    def test_record_logged_out(self):
        self.client.logout()
        res = self.client.post(self.url)
        eq_(res.status_code, 302)

    @mock.patch('mkt.detail.views.send_request')
    @mock.patch('mkt.detail.views.cef')
    def test_record_metrics(self, cef, send_request):
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(send_request.call_args[0][0], 'install')
        eq_(send_request.call_args[0][2], {'app-domain': u'cbc.ca',
                                           'app-id': self.addon.pk})

    @mock.patch('mkt.detail.views.cef')
    def test_cef_logs(self, cef):
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(len(cef.call_args_list), 2)
        eq_([x[0][2] for x in cef.call_args_list],
            ['request', 'sign'])

        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(len(cef.call_args_list), 3)
        eq_([x[0][2] for x in cef.call_args_list],
            ['request', 'sign', 'request'])

    @mock.patch('mkt.detail.views.cef')
    def test_record_install(self, cef):
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.user.installed_set.count(), 1)

    @mock.patch('mkt.detail.views.cef')
    def test_record_multiple_installs(self, cef):
        self.client.post(self.url)
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.user.installed_set.count(), 1)

    @mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                       amo.tests.AMOPaths.sample_key())
    @mock.patch('mkt.detail.views.cef')
    def test_record_receipt(self, cef):
        res = self.client.post(self.url)
        content = json.loads(res.content)
        assert content.get('receipt'), content


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


class TestReportAbuse(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Webapp.objects.get(id=337141)
        self.url = self.webapp.get_detail_url('abuse')

    def test_get(self):
        # TODO: Uncomment Report Abuse gets ported to mkt.
        raise SkipTest
        r = self.client.get(self.url)
        eq_(r.status_code, 200)

    def test_submit(self):
        # TODO: Uncomment Report Abuse gets ported to mkt.
        raise SkipTest
        self.client.login(username='regular@mozilla.com', password='password')
        r = self.client.post(self.url, {'text': 'this is some rauncy ish'})
        self.assertRedirects(r, self.webapp.get_detail_url())
