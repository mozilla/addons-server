from nose.tools import eq_

import amo
from amo.urlresolvers import reverse
from mkt.submit.tests.test_views import BasePackagedAppTest


class TestDownload(BasePackagedAppTest):
    fixtures = ['base/apps', 'base/users', 'base/platforms',
                'webapps/337141-steamcube']

    def setUp(self):
        super(TestDownload, self).setUp()
        super(TestDownload, self).setup_files()
        self.url = reverse('downloads.file', args=[self.file.pk])

    def test_download(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        assert 'x-sendfile' in res._headers

    def test_disabled(self):
        self.app.update(status=amo.STATUS_DISABLED)
        eq_(self.client.get(self.url).status_code, 404)

    def test_disabled_but_owner(self):
        self.client.login(username='steamcube@mozilla.com',
                          password='password')
        eq_(self.client.get(self.url).status_code, 200)

    def test_disabled_but_admin(self):
        self.client.login(username='admin@mozilla.com',
                          password='password')
        eq_(self.client.get(self.url).status_code, 200)

    def test_not_webapp(self):
        self.app.update(type=amo.ADDON_EXTENSION)
        eq_(self.client.get(self.url).status_code, 404)
