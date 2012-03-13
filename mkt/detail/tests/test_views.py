import json

from django.conf import settings

import mock
from nose.tools import eq_

import amo
import amo.tests
from amo.urlresolvers import reverse
from users.models import UserProfile


@mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                   amo.tests.AMOPaths.sample_key())
class TestInstall(amo.tests.TestCase):
    fixtures = ['base/users']

    def setUp(self):
        self.addon = amo.tests.addon_factory(type=amo.ADDON_WEBAPP,
            manifest_url='http://cbc.ca/manifest')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')
        self.url = reverse('detail.record', args=[self.addon.app_slug])
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')

    def test_not_record_addon(self):
        self.addon.update(type=amo.ADDON_EXTENSION)
        self.client.post(self.url)
        eq_(self.user.installed_set.count(), 0)

    def test_record_logged_out(self):
        self.client.logout()
        res = self.client.post(self.url)
        eq_(res.status_code, 302)

    def test_record_install(self):
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.user.installed_set.count(), 1)

    def test_record_multiple_installs(self):
        self.client.post(self.url)
        res = self.client.post(self.url)
        eq_(res.status_code, 200)
        eq_(self.user.installed_set.count(), 1)

    @mock.patch.object(settings, 'WEBAPPS_RECEIPT_KEY',
                       amo.tests.AMOPaths.sample_key())
    def test_record_receipt(self):
        res = self.client.post(self.url)
        content = json.loads(res.content)
        assert content.get('receipt'), content
