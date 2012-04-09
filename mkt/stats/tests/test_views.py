import datetime
import json

from nose.tools import eq_

import amo
import amo.tests
from amo.urlresolvers import reverse
from addons.models import Addon
from mkt.webapps.models import Installed
from stats import search
from users.models import UserProfile


class TestInstalled(amo.tests.ESTestCase):
    es = True
    fixtures = ['base/users', 'webapps/337141-steamcube']

    def setUp(self):
        self.today = datetime.date.today()
        self.webapp = Addon.objects.get(pk=337141)
        self.user = UserProfile.objects.get(pk=999)
        self.client.login(username='admin@mozilla.com', password='password')
        self.in_ = Installed.objects.create(addon=self.webapp, user=self.user)
        Installed.index(search.extract_installed_count(self.in_),
                        id=self.in_.pk)
        self.refresh('users_install')

    def get_url(self, start, end, fmt='json'):
        return reverse('mkt.stats.installs_series',
                       args=[self.webapp.app_slug, 'day',
                             start.strftime('%Y%m%d'),
                             end.strftime('%Y%m%d'), fmt])

    def test_installed(self):
        res = self.client.get(self.get_url(self.today, self.today))
        data = json.loads(res.content)
        eq_(data[0]['count'], 1)

    def tests_installed_anon(self):
        self.client.logout()
        res = self.client.get(self.get_url(self.today, self.today))
        eq_(res.status_code, 403)
