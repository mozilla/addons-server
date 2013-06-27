import json

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.urlresolvers import reverse

import mock
from nose.tools import eq_, ok_
from receipts.receipts import Receipt
from tastypie import http
from tastypie.bundle import Bundle
from test_utils import RequestFactory

import amo.tests

from addons.models import Addon, AddonUser
from constants.payments import CONTRIB_NO_CHARGE
from devhub.models import AppLog
from mkt.api.base import list_url
from mkt.api.tests.test_oauth import BaseOAuth
from mkt.constants import apps
from mkt.receipts.api import HttpPaymentRequired, ReceiptResource
from mkt.site.fixtures import fixture
from users.models import UserProfile


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestAPI(BaseOAuth):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestAPI, self).setUp(api_name='receipts')
        self.addon = Addon.objects.get(pk=337141)
        self.url = list_url('install')
        self.data = json.dumps({'app': self.addon.pk})
        self.profile = self.user.get_profile()

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.url), 'post')

    def post(self, anon=False):
        client = self.client if not anon else self.anon
        return client.post(self.url, data=self.data)

    def test_no_app(self):
        self.data = json.dumps({'app': 0})
        eq_(self.post().status_code, 400)

    def test_app_slug(self):
        self.data = json.dumps({'app': self.addon.app_slug})
        eq_(self.post().status_code, 201)

    def test_record_logged_out(self):
        res = self.post(anon=True)
        eq_(res.status_code, 201)
        eq_(res.json['receipt'], None)

    @mock.patch('mkt.receipts.api.receipt_cef.log')
    def test_cef_logs(self, cef):
        eq_(self.post().status_code, 201)
        eq_(len(cef.call_args_list), 1)
        eq_([x[0][2] for x in cef.call_args_list], ['sign'])

    @mock.patch('mkt.receipts.api.record_action')
    @mock.patch('mkt.receipts.api.receipt_cef.log')
    def test_record_metrics(self, cef, record_action):
        res = self.post()
        eq_(res.status_code, 201)
        record_action.assert_called_with('install', mock.ANY, {
            'app-domain': u'http://micropipes.com',
            'app-id': self.addon.pk, 'anonymous': False})

    @mock.patch('mkt.receipts.api.record_action')
    @mock.patch('mkt.receipts.api.receipt_cef.log')
    def test_record_metrics_packaged_app(self, cef, record_action):
        # Mimic packaged app.
        self.addon.update(is_packaged=True, manifest_url=None, app_domain=None)
        res = self.post()
        eq_(res.status_code, 201)
        record_action.assert_called_with('install', mock.ANY, {
            'app-domain': None, 'app-id': self.addon.pk, 'anonymous': False})

    @mock.patch('mkt.receipts.views.receipt_cef.log')
    def test_log_metrics(self, cef):
        eq_(self.post().status_code, 201)
        logs = AppLog.objects.filter(addon=self.addon)
        eq_(logs.count(), 1)
        eq_(logs[0].activity_log.action, amo.LOG.INSTALL_ADDON.id)


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestDevhubAPI(BaseOAuth):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        super(TestDevhubAPI, self).setUp(api_name='receipts')
        self.data = json.dumps({'manifest_url': 'http://foo.com',
                                'receipt_type': 'expired'})
        self.url = list_url('test')

    def test_has_cors(self):
        self.assertCORS(self.client.get(self.url), 'post')

    def test_decode(self):
        res = self.anon.post(self.url, data=self.data)
        eq_(res.status_code, 201)
        data = json.loads(res.content)
        receipt = Receipt(data['receipt'].encode('ascii')).receipt_decoded()
        eq_(receipt['typ'], u'test-receipt')

    @mock.patch('mkt.receipts.api.receipt_cef.log')
    def test_cef_log(self, cef):
        self.anon.post(self.url, data=self.data)
        cef.assert_called_with(mock.ANY, None, 'sign', 'Test receipt signing')


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestReceipt(amo.tests.TestCase):
    fixtures = fixture('user_2519', 'webapp_337141')

    def setUp(self):
        self.addon = Addon.objects.get(pk=337141)
        self.bundle = Bundle(data={'app': self.addon.pk})
        self.profile = UserProfile.objects.get(pk=2519)
        self.resource = ReceiptResource()

    def get_request(self, profile):
        request = RequestFactory().post('/')
        if not profile:
            request.user = AnonymousUser()
        else:
            request.user = profile.user
            request.amo_user = profile
        return request

    def handle(self, profile):
        return self.resource.handle(self.bundle, self.get_request(profile))

    def test_pending_free_for_developer(self):
        AddonUser.objects.create(addon=self.addon, user=self.profile)
        self.addon.update(status=amo.STATUS_PENDING)
        ok_(self.handle(self.profile))

    def test_pending_free_for_anonymous(self):
        self.addon.update(status=amo.STATUS_PENDING)
        with self.assertImmediate(http.HttpForbidden):
            ok_(self.handle(None))

    def test_pending_paid_for_developer(self):
        AddonUser.objects.create(addon=self.addon, user=self.profile)
        self.addon.update(status=amo.STATUS_PENDING,
                          premium_type=amo.ADDON_PREMIUM)
        ok_(self.handle(self.profile))
        eq_(self.profile.installed_set.all()[0].install_type,
            apps.INSTALL_TYPE_DEVELOPER)

    def test_pending_paid_for_anonymous(self):
        self.addon.update(status=amo.STATUS_PENDING,
                          premium_type=amo.ADDON_PREMIUM)
        with self.assertImmediate(http.HttpForbidden):
            ok_(self.handle(None))

    def test_not_record_addon(self):
        self.addon.update(type=amo.ADDON_EXTENSION)
        with self.assertImmediate(http.HttpBadRequest):
            ok_(self.handle(self.profile))

    @mock.patch('mkt.webapps.models.Webapp.has_purchased')
    def test_paid(self, has_purchased):
        has_purchased.return_value = True
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        ok_(self.handle(self.profile))

    def test_own_payments(self):
        self.addon.update(premium_type=amo.ADDON_OTHER_INAPP)
        ok_(self.handle(self.profile))

    def test_no_charge(self):
        self.make_premium(self.addon, '0.00')
        ok_(self.handle(self.profile))
        eq_(self.profile.installed_set.all()[0].install_type,
            apps.INSTALL_TYPE_USER)
        eq_(self.profile.addonpurchase_set.all()[0].type,
            CONTRIB_NO_CHARGE)

    @mock.patch('mkt.webapps.models.Webapp.has_purchased')
    def test_not_paid(self, has_purchased):
        has_purchased.return_value = False
        self.addon.update(premium_type=amo.ADDON_PREMIUM)
        with self.assertImmediate(HttpPaymentRequired):
            ok_(self.handle(self.profile))

    @mock.patch('mkt.receipts.api.receipt_cef.log')
    def test_record_install(self, cef):
        ok_(self.handle(self.profile))
        installed = self.profile.installed_set.all()
        eq_(len(installed), 1)
        eq_(installed[0].install_type, apps.INSTALL_TYPE_USER)

    @mock.patch('mkt.receipts.api.receipt_cef.log')
    def test_record_multiple_installs(self, cef):
        ok_(self.handle(self.profile))
        ok_(self.handle(self.profile))
        eq_(self.profile.installed_set.count(), 1)

    @mock.patch('mkt.receipts.api.receipt_cef.log')
    def test_record_receipt(self, cef):
        res = self.handle(self.profile)
        ok_(Receipt(res).receipt_decoded())


class TestReissue(amo.tests.TestCase):

    def setUp(self):
        self.url = reverse('receipt.reissue')

    def test_get(self):
        eq_(self.client.get(self.url).status_code, 405)

    def test_reissue(self):
        res = self.client.post(self.url, data={})
        eq_(res.status_code, 200)
        eq_(json.loads(res.content)['status'], 'not-implemented')
