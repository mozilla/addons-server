from nose.tools import eq_
import test_utils

import amo
from amo.helpers import url
from applications.models import AppVersion, Application


class TestAppVersion(test_utils.TestCase):

    def test_major_minor(self):
        """Check that major/minor/alpha is getting set."""
        v = AppVersion(version='3.0.12b2')
        eq_(v.major, 3)
        eq_(v.minor1, 0)
        eq_(v.minor2, 12)
        eq_(v.minor3, None)
        eq_(v.alpha, 'b')
        eq_(v.alpha_ver, 2)

        v = AppVersion(version='3.6.1apre2+')
        eq_(v.major, 3)
        eq_(v.minor1, 6)
        eq_(v.minor2, 1)
        eq_(v.alpha, 'a')
        eq_(v.pre, 'pre')
        eq_(v.pre_ver, 2)

        v = AppVersion(version='')
        eq_(v.major, None)
        eq_(v.minor1, None)
        eq_(v.minor2, None)
        eq_(v.minor3, None)


class TestApplication(test_utils.TestCase):
    fixtures = ['applications/all_apps.json']

    def test_string_representation(self):
        """
        Check that the string representation of the app model instances
        matches out constants
        """
        for static_app in amo.APP_USAGE:
            model_app = Application.objects.get(id=static_app.id)
            eq_(unicode(model_app), unicode(static_app.pretty))


class TestViews(test_utils.TestCase):
    fixtures = ['base/appversion']

    def test_appversions(self):
        eq_(self.client.get(url('apps.appversions')).status_code, 200)

    def test_appversions_feed(self):
        eq_(self.client.get(url('apps.appversions.rss')).status_code, 200)
