from nose.plugins.skip import SkipTest
from nose.tools import eq_
from pyquery import PyQuery as pq
import waffle

import amo
import amo.tests
from addons.models import Addon


class TestAppStatus(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.client.login(username='admin@mozilla.com', password='password')
        self.webapp = Addon.objects.get(id=337141)
        self.url = self.webapp.get_dev_url('versions')

    def test_nav_link(self):
        r = self.client.get(self.url)
        eq_(pq(r.content)('#edit-addon-nav li.selected a').attr('href'),
            self.url)

    def test_items(self):
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#version-status').length, 1)
        eq_(doc('#version-list').length, 0)
        eq_(doc('#delete-addon').length, 0)
        eq_(doc('#modal-delete').length, 0)
        eq_(doc('#modal-disable').length, 1)

    def test_soft_delete_items(self):
        waffle.models.Switch.objects.create(name='soft_delete', active=True)
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#version-status').length, 1)
        eq_(doc('#version-list').length, 0)
        eq_(doc('#delete-addon').length, 1)
        eq_(doc('#modal-delete').length, 1)
        eq_(doc('#modal-disable').length, 1)

    def test_delete_link(self):
        # When we can reauth with Persona, unskip this.
        raise SkipTest

        # Delete link is visible for only incomplete apps.
        self.webapp.update(status=amo.STATUS_NULL)
        doc = pq(self.client.get(self.url).content)
        eq_(doc('#delete-addon').length, 1)
        eq_(doc('#modal-delete').length, 1)

    def test_no_version_list(self):
        r = self.client.get(self.url)
        doc = pq(r.content)
        eq_(doc('#version-list').length, 0)

    def test_pending(self):
        # If settings.WEBAPPS_RESTRICTED = True, apps begin life as pending.
        self.webapp.update(status=amo.STATUS_PENDING)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#version-status .status-none').length, 1)

    def test_public(self):
        # If settings.WEBAPPS_RESTRICTED = False, apps begin life as public.
        eq_(self.webapp.status, amo.STATUS_PUBLIC)
        r = self.client.get(self.url)
        eq_(r.status_code, 200)
        eq_(pq(r.content)('#version-status .status-fully-approved').length, 1)
