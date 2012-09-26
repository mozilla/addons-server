import mock
from nose.tools import eq_

from django.conf import settings

import amo
from amo.urlresolvers import reverse
from lib.crypto import packaged
from lib.crypto.tests import mock_sign
from mkt.submit.tests.test_views import BasePackagedAppTest
from mkt.webapps.models import Webapp


class TestDownload(BasePackagedAppTest):
    fixtures = ['base/apps', 'base/users', 'base/platforms',
                'webapps/337141-steamcube']

    def setUp(self):
        super(TestDownload, self).setUp()
        super(TestDownload, self).setup_files()
        self.url = reverse('downloads.file', args=[self.file.pk])

    @mock.patch.object(packaged, 'sign', mock_sign)
    def test_download(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        assert 'x-sendfile' in res._headers

    def test_disabled(self):
        self.app.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.url).status_code, 404)

    @mock.patch.object(packaged, 'sign', mock_sign)
    def test_disabled_but_owner(self):
        self.client.login(username='steamcube@mozilla.com',
                          password='password')
        eq_(self.client.get(self.url).status_code, 200)

    @mock.patch.object(packaged, 'sign', mock_sign)
    def test_disabled_but_admin(self):
        self.client.login(username='admin@mozilla.com',
                          password='password')
        eq_(self.client.get(self.url).status_code, 200)

    def test_not_webapp(self):
        self.app.update(type=amo.ADDON_EXTENSION)
        eq_(self.client.get(self.url).status_code, 404)


class TestBlockedDownload(amo.tests.TestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.app = Webapp.objects.get(pk=337141)
        self.app.update(is_packaged=True)
        self.url = reverse('downloads.blocked_packaged_app')

    @mock.patch.object(settings, 'BLOCKED_PACKAGE_PATH', '/path/to/block.zip')
    def test_download(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        eq_(res['X-SENDFILE'], '/path/to/block.zip')
        eq_(res['Content-type'], 'application/zip')

    # We don't care what status of type the package is, always return the
    # blocked app package.

    def test_disabled(self):
        self.app.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.url).status_code, 200)

    def test_not_webapp(self):
        self.app.update(type=amo.ADDON_EXTENSION)
        eq_(self.client.get(self.url).status_code, 200)
