from nose.tools import eq_

import amo
import amo.tests
from addons.models import Addon
from amo.urlresolvers import reverse


class TestDownload(amo.tests.TestCase):
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.webapp = Addon.objects.get(pk=337141)
        self.webapp.update(is_packaged=True)
        self.file = self.webapp.get_latest_file()
        self.url = reverse('downloads.file', args=[self.file.pk])

    def test_download(self):
        res = self.client.get(self.url)
        eq_(res.status_code, 200)
        assert 'x-sendfile' in res._headers

    def test_disabled(self):
        self.webapp.update(status=amo.STATUS_DISABLED)
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
        self.webapp.update(type=amo.ADDON_EXTENSION)
        eq_(self.client.get(self.url).status_code, 404)
