import mock
from nose import SkipTest
from nose.tools import eq_

from django.conf import settings

import amo
from amo.urlresolvers import reverse
from lib.crypto import packaged
from lib.crypto.tests import mock_sign
from mkt.submit.tests.test_views import BasePackagedAppTest


class TestDownload(BasePackagedAppTest):
    fixtures = ['base/apps', 'base/users', 'base/platforms',
                'webapps/337141-steamcube']

    def setUp(self):
        super(TestDownload, self).setUp()
        super(TestDownload, self).setup_files()
        self.url = reverse('downloads.file', args=[self.file.pk])

    @mock.patch.object(packaged, 'sign', mock_sign)
    def test_download(self):
        if not settings.XSENDFILE:
            raise SkipTest
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        assert settings.XSENDFILE_HEADER in res

    def test_disabled(self):
        self.app.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.url).status_code, 404)

    def test_not_public(self):
        self.file.update(status=amo.STATUS_PENDING)
        eq_(self.client.get(self.url).status_code, 404)

    @mock.patch('lib.crypto.packaged.sign')
    def test_not_public_but_owner(self, sign):
        self.client.login(username='steamcube@mozilla.com',
                          password='password')
        self.file.update(status=amo.STATUS_PENDING)
        eq_(self.client.get(self.url).status_code, 200)
        assert not sign.called

    @mock.patch('lib.crypto.packaged.sign')
    def test_not_public_not_owner(self, sign):
        self.client.login(username='regular@mozilla.com',
                          password='password')
        self.file.update(status=amo.STATUS_PENDING)
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

    @mock.patch.object(packaged, 'sign', mock_sign)
    def test_file_blocklisted(self):
        if not settings.XSENDFILE:
            raise SkipTest
        self.file.update(status=amo.STATUS_BLOCKED)
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        assert settings.XSENDFILE_HEADER in res
