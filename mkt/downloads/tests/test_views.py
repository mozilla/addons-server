import mock
from nose import SkipTest
from nose.tools import eq_

from django.conf import settings

import amo
from amo.urlresolvers import reverse
from lib.crypto import packaged
from lib.crypto.tests import mock_sign
from mkt.submit.tests.test_views import BasePackagedAppTest
from users.models import UserProfile


class Download(BasePackagedAppTest):

    def setUp(self):
        super(Download, self).setUp()
        super(Download, self).setup_files()
        self.url = reverse('downloads.file', args=[self.file.pk])


class TestDownload(Download):

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


class TestDownloadPremium(Download):

    def setUp(self):
        super(TestDownloadPremium, self).setUp()
        self.make_premium(self.app)

    def test_anon(self):
        self.client.logout()
        eq_(self.client.get(self.url).status_code, 403)

    def test_not_purchased(self):
        eq_(self.client.get(self.url).status_code, 402)

    def test_purchased(self):
        self.app.addonpurchase_set.create(user_id=999)
        eq_(self.client.get(self.url).status_code, 200)

    def test_developer(self):
        self.app.addonuser_set.create(user_id=999, role=amo.AUTHOR_ROLE_VIEWER)
        eq_(self.client.get(self.url).status_code, 200)

    def test_reviewer(self):
        self.grant_permission(999, 'Apps:Review')
        eq_(self.client.get(self.url).status_code, 200)

    def test_other_reviewer(self):
        self.grant_permission(999, 'Themes:Review')
        eq_(self.client.get(self.url).status_code, 402)
