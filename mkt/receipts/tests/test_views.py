# -*- coding: utf8 -*-
import json
import uuid

from django.conf import settings

import mock
from nose.tools import eq_
from pyquery import PyQuery as pq

from addons.models import AddonUser
import amo
import amo.tests
from amo.urlresolvers import reverse
from devhub.models import AppLog
from mkt.constants import apps
from mkt.site.fixtures import fixture
from mkt.webapps.models import Webapp
from users.models import UserProfile
from zadmin.models import DownloadSource


class TestReissue(amo.tests.TestCase):
    fixtures = fixture('webapp_337141')

    def setUp(self):
        self.webapp = Webapp.objects.get(pk=337141)
        assert self.client.login(username='steamcube@mozilla.com',
                                 password='password')
        self.url = self.webapp.get_purchase_url('reissue')

    def test_reissue_logout(self):
        self.client.logout()
        res = self.client.get(self.url)
        eq_(res.status_code, 302)

    def test_reissue(self):
        res = self.client.get(self.url)
        eq_(res.context['reissue'], True)

    @mock.patch('addons.models.Addon.has_purchased')
    def test_reissue_premium_not_purchased(self, has_purchased):
        self.make_premium(self.webapp)
        has_purchased.return_value = False
        res = self.client.get(self.url)
        eq_(res.context['reissue'], False)
        eq_(len(pq(res.content)('button.install')), 0)

    @mock.patch('addons.models.Addon.has_purchased')
    def test_reissue_premium_purchased(self, has_purchased):
        self.make_premium(self.webapp)
        has_purchased.return_value = True
        res = self.client.get(self.url)
        eq_(res.context['reissue'], True)
        eq_(len(pq(res.content)('button.install')), 1)


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestInstall(amo.tests.TestCase):
    fixtures = fixture('user_999', 'user_editor', 'user_editor_group',
                       'group_editor')

    def setUp(self):
        self.addon = amo.tests.app_factory(manifest_url='http://cbc.ca/man')
        self.url = self.addon.get_detail_url('record')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        assert self.client.login(username=self.user.email, password='password')

    def test_pending_free_for_reviewer(self):
        self.addon.update(status=amo.STATUS_PENDING)
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        eq_(self.client.post(self.url).status_code, 200)

    def test_pending_free_for_developer(self):
        AddonUser.objects.create(addon=self.addon, user=self.user)
        self.addon.update(status=amo.STATUS_PENDING)
        eq_(self.client.post(self.url).status_code, 200)

    def test_pending_free_for_anonymous(self):
        self.addon.update(status=amo.STATUS_PENDING)
        eq_(self.client.post(self.url).status_code, 404)

    def test_pending_paid_for_reviewer(self):
        self.addon.update(status=amo.STATUS_PENDING,
                          premium_type=amo.ADDON_PREMIUM)
        assert self.client.login(username='editor@mozilla.com',
                                 password='password')
        eq_(self.client.post(self.url).status_code, 200)
        # Because they aren't using reviewer tools, they'll get a normal
        # install record and receipt.
        eq_(self.addon.installed.all()[0].install_type,
            apps.INSTALL_TYPE_USER)

    def test_pending_paid_for_admin(self):
        self.addon.update(status=amo.STATUS_PENDING,
                          premium_type=amo.ADDON_PREMIUM)
        self.grant_permission(self.user, '*:*')
        eq_(self.client.post(self.url).status_code, 200)
        # Check ownership ignores admin users.
        eq_(self.addon.installed.all()[0].install_type,
            apps.INSTALL_TYPE_USER)

    def test_pending_paid_for_developer(self):
        AddonUser.objects.create(addon=self.addon, user=self.user)
        self.addon.update(status=amo.STATUS_PENDING,
                          premium_type=amo.ADDON_PREMIUM)
        eq_(self.client.post(self.url).status_code, 200)
        eq_(self.user.installed_set.all()[0].install_type,
            apps.INSTALL_TYPE_DEVELOPER)

    def test_pending_paid_for_anonymous(self):
        self.addon.update(status=amo.STATUS_PENDING,
                          premium_type=amo.ADDON_PREMIUM)
        eq_(self.client.post(self.url).status_code, 404)

    def test_not_record_addon(self):
        self.addon.update(type=amo.ADDON_EXTENSION)
        res = self.client.post(self.url)
        eq_(res.status_code, 404)
        eq_(self.user.installed_set.count(), 0)

    @mock.patch('mkt.webapps.models.Webapp.has_purchased')
    def test_paid(self, has_purchased):
        has_purchased.return_value = True
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        eq_(self.client.post(self.url).status_code, 200)

    def test_own_payments(self):
        self.addon.update(premium_type=amo.ADDON_OTHER_INAPP)
        eq_(self.client.post(self.url).status_code, 200)

    @mock.patch('mkt.webapps.models.Webapp.has_purchased')
    def test_not_paid(self, has_purchased):
        has_purchased.return_value = False
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        eq_(self.client.post(self.url).status_code, 403)

    def test_record_logged_out(self):
        self.client.logout()
        res = self.client.post(self.url)
        eq_(res.status_code, 200)

    @mock.patch('mkt.receipts.views.receipt_cef.log')
    def test_log_metrics(self, cef):
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        logs = AppLog.objects.filter(addon=self.addon)
        eq_(logs.count(), 1)
        eq_(logs[0].activity_log.action, amo.LOG.INSTALL_ADDON.id)

    @mock.patch('mkt.receipts.views.send_request')
    @mock.patch('mkt.receipts.views.receipt_cef.log')
    def test_record_metrics(self, cef, send_request):
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(send_request.call_args[0][0], 'install')
        eq_(send_request.call_args[0][2], {'app-domain': u'http://cbc.ca',
                                           'app-id': self.addon.pk,
                                           'anonymous': False})

    @mock.patch('mkt.receipts.views.send_request')
    @mock.patch('mkt.receipts.views.receipt_cef.log')
    @mock.patch.object(settings, 'SITE_URL', 'http://test.com')
    def test_record_metrics_packaged_app(self, cef, send_request):
        # Mimic packaged app.
        self.addon.update(is_packaged=True, manifest_url=None)
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(send_request.call_args[0][0], 'install')
        eq_(send_request.call_args[0][2], {
            'app-domain': u'http://test.com',
            'app-id': self.addon.pk,
            'anonymous': False})

    @mock.patch('mkt.receipts.views.receipt_cef.log')
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

    @mock.patch('mkt.receipts.views.receipt_cef.log')
    def test_record_install(self, cef):
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        installed = self.user.installed_set.all()
        eq_(len(installed), 1)
        eq_(installed[0].install_type, apps.INSTALL_TYPE_USER)

    @mock.patch('mkt.receipts.views.receipt_cef.log')
    def test_record_multiple_installs(self, cef):
        self.client.post(self.url)
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.user.installed_set.count(), 1)

    @mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                       amo.tests.AMOPaths.sample_key())
    @mock.patch('mkt.receipts.views.receipt_cef.log')
    def test_record_receipt(self, cef):
        res = self.client.post(self.url)
        content = json.loads(res.content)
        assert content.get('receipt'), content

    def test_installed_client_data(self):
        download_source = DownloadSource.objects.create(name='mkt-home')
        device_type = 'mobile'
        user_agent = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:16.0)'

        self.addon.update(type=amo.ADDON_WEBAPP)
        res = self.client.post(self.url,
                               data={'device_type': device_type,
                                     'is_chromeless': False,
                                     'src': download_source.name},
                               HTTP_USER_AGENT=user_agent)

        eq_(res.status_code, 200)
        eq_(self.user.installed_set.count(), 1)
        ins = self.user.installed_set.get()
        eq_(ins.client_data.download_source, download_source)
        eq_(ins.client_data.device_type, device_type)
        eq_(ins.client_data.user_agent, user_agent)
        eq_(ins.client_data.is_chromeless, False)
        eq_(not ins.client_data.language, False)
        eq_(not ins.client_data.region, False)


class TestReceiptVerify(amo.tests.TestCase):
    fixtures = fixture('user_999', 'user_editor', 'user_editor_group',
                       'group_editor')

    def setUp(self):
        super(TestReceiptVerify, self).setUp()
        self.app = Webapp.objects.create(app_slug='foo', guid=uuid.uuid4())
        self.url = reverse('receipt.verify',
                           args=[self.app.guid])
        self.log = AppLog.objects.filter(addon=self.app)
        self.reviewer = UserProfile.objects.get(pk=5497308)

    def get_mock(self, user=None, **kwargs):
        self.verify = mock.Mock()
        self.verify.return_value = json.dumps(kwargs)
        self.verify.invalid.return_value = json.dumps({'status': 'invalid'})
        self.verify.user_id = user.pk if user else self.reviewer.pk
        return self.verify

    def test_post_required(self):
        eq_(self.client.get(self.url).status_code, 405)

    @mock.patch('mkt.receipts.views.Verify')
    def test_empty(self, verify):
        vfy = self.get_mock(user=self.reviewer, status='invalid')
        # Because the receipt was empty, this never got set and so
        # we didn't log it.
        vfy.user_id = None
        verify.return_value = vfy
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.log.count(), 0)
        eq_(json.loads(res.content)['status'], 'invalid')

    @mock.patch('mkt.receipts.views.Verify')
    def test_good(self, verify):
        verify.return_value = self.get_mock(user=self.reviewer, status='ok')
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.log.count(), 1)
        eq_(json.loads(res.content)['status'], 'ok')

    @mock.patch('mkt.receipts.views.Verify')
    def test_not_reviewer(self, verify):
        self.reviewer.groups.clear()
        verify.return_value = self.get_mock(user=self.reviewer, status='ok')
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.log.count(), 0)
        eq_(json.loads(res.content)['status'], 'invalid')

    @mock.patch('mkt.receipts.views.Verify')
    def test_not_there(self, verify):
        verify.return_value = self.get_mock(user=self.reviewer, status='ok')
        self.reviewer.delete()
        res = self.client.post(self.url)
        eq_(res['Access-Control-Allow-Origin'], '*')
        eq_(json.loads(res.content)['status'], 'invalid')

    @mock.patch('mkt.receipts.views.Verify')
    def test_logs(self, verify):
        verify.return_value = self.get_mock(user=self.reviewer, status='ok')
        eq_(self.log.count(), 0)
        res = self.client.post(self.url)
        eq_(self.log.count(), 1)
        eq_(res.status_code, 200)

    @mock.patch('mkt.receipts.views.Verify')
    def test_logs_developer(self, verify):
        developer = UserProfile.objects.get(pk=999)
        AddonUser.objects.create(addon=self.app, user=developer)
        verify.return_value = self.get_mock(user=developer, status='ok')
        res = self.client.post(self.url)
        eq_(res['Access-Control-Allow-Origin'], '*')
        eq_(self.log.count(), 1)
        eq_(res.status_code, 200)


class TestReceiptIssue(amo.tests.TestCase):
    fixtures = fixture('user_999', 'user_editor', 'user_editor_group',
                       'group_editor', 'webapp_337141')

    def setUp(self):
        super(TestReceiptIssue, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.url = reverse('receipt.issue', args=[self.app.app_slug])
        self.reviewer = UserProfile.objects.get(pk=5497308)
        self.user = UserProfile.objects.get(pk=999)

    @mock.patch('mkt.receipts.views.create_receipt')
    def test_issued(self, create_receipt):
        create_receipt.return_value = 'foo'
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(create_receipt.call_args[1]['flavour'], 'reviewer')
        eq_(self.reviewer.installed_set.all()[0].install_type,
            apps.INSTALL_TYPE_REVIEWER)

    def test_get(self):
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 405)

    def test_issued_anon(self):
        res = self.client.post(self.url)
        eq_(res.status_code, 403)

    def test_issued_not_reviewer(self):
        self.client.login(username=self.user, password='password')
        res = self.client.post(self.url)
        eq_(res.status_code, 403)

    @mock.patch('mkt.receipts.views.create_receipt')
    def test_issued_developer(self, create_receipt):
        create_receipt.return_value = 'foo'
        AddonUser.objects.create(user=self.user, addon=self.app)
        self.client.login(username=self.user.email, password='password')
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(create_receipt.call_args[1]['flavour'], 'developer')
        eq_(self.user.installed_set.all()[0].install_type,
            apps.INSTALL_TYPE_DEVELOPER)

    @mock.patch('mkt.receipts.views.create_receipt')
    def test_unicode_name(self, create_receipt):
        """
        Regression test to ensure that the CEF log works. Pass through the
        app.pk instead of the full unicode name, until the CEF library is
        fixed, or metlog is used.
        """
        create_receipt.return_value = 'foo'
        self.app.name = u'\u0627\u0644\u062a\u0637\u0628-news'
        self.app.save()

        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.post(self.url)
        eq_(res.status_code, 200)


class TestReceiptCheck(amo.tests.TestCase):
    fixtures = fixture('user_999', 'user_editor', 'user_editor_group',
                       'group_editor', 'webapp_337141')

    def setUp(self):
        super(TestReceiptCheck, self).setUp()
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(status=amo.STATUS_PENDING)
        self.url = reverse('receipt.check',
                           args=[self.app.guid])
        self.reviewer = UserProfile.objects.get(pk=5497308)
        self.user = UserProfile.objects.get(pk=999)

    def test_anon(self):
        eq_(self.client.get(self.url).status_code, 302)

    def test_not_reviewer(self):
        self.client.login(username=self.user.email, password='password')
        eq_(self.client.get(self.url).status_code, 403)

    def test_not_there(self):
        self.client.login(username=self.reviewer.email, password='password')
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], False)

    def test_there(self):
        self.client.login(username=self.reviewer.email, password='password')
        amo.log(amo.LOG.RECEIPT_CHECKED, self.app, user=self.reviewer)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], True)
