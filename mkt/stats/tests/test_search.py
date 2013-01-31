from datetime import datetime

from nose.tools import eq_

import amo.tests
from mkt.constants import apps
from mkt.site.fixtures import fixture
from mkt.stats import search
from mkt.webapps.models import Installed
from users.models import UserProfile


class InstalledTests(amo.tests.TestCase):
    fixtures = fixture('user_999')

    def setUp(self):
        self.user = UserProfile.objects.get(username='regularuser')
        self.first_app = amo.tests.app_factory(name='public',
            app_slug='pub', type=1, status=4, public_stats=True)
        self.second_app = amo.tests.app_factory(name='private',
            app_slug='priv', type=1, status=4, public_stats=False)

    def test_no_installs(self):
        data = {'created': datetime.now(),
                'addon': self.first_app.id}
        result = search.get_installed_daily(data)
        eq_(result['date'], data['created'].date())
        eq_(result['addon'], data['addon'])
        eq_(result['count'], 0)

    def test_only_one_app(self):
        Installed.objects.create(addon=self.first_app, user=self.user,
                                 install_type=apps.INSTALL_TYPE_USER)
        data = {'created': datetime.now(),
                'addon': self.first_app.id}
        result = search.get_installed_daily(data)
        eq_(result['date'], data['created'].date())
        eq_(result['addon'], data['addon'])
        eq_(result['count'], 1)

    def test_multiple_installs(self):
        # Due to the unique together we use different install types to deal
        # with that constraint.
        Installed.objects.create(addon=self.first_app, user=self.user,
                                 install_type=apps.INSTALL_TYPE_USER)
        Installed.objects.create(addon=self.first_app, user=self.user,
                                 install_type=apps.INSTALL_TYPE_DEVELOPER)
        data = {'created': datetime.now(),
                'addon': self.first_app.id}
        result = search.get_installed_daily(data)
        eq_(result['date'], data['created'].date())
        eq_(result['addon'], data['addon'])
        eq_(result['count'], 2)

    def test_two_apps(self):
        Installed.objects.create(addon=self.first_app, user=self.user,
                                 install_type=apps.INSTALL_TYPE_USER)
        Installed.objects.create(addon=self.second_app, user=self.user,
                                 install_type=apps.INSTALL_TYPE_USER)
        data = {'created': datetime.now(),
                'addon': self.first_app.id}
        result = search.get_installed_daily(data)
        eq_(result['date'], data['created'].date())
        eq_(result['addon'], data['addon'])
        eq_(result['count'], 1)
