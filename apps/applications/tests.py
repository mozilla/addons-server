import json

from django.core.management import call_command
from django.core.files.storage import default_storage as storage
from nose.tools import eq_

import amo
import amo.tests
from amo.helpers import url
from applications.models import AppVersion, Application
from applications.management.commands import dump_apps


class TestAppVersion(amo.tests.TestCase):

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


class TestApplication(amo.tests.TestCase):
    fixtures = ['applications/all_apps.json']

    def test_string_representation(self):
        """
        Check that the string representation of the app model instances
        matches out constants
        """
        for static_app in amo.APP_USAGE:
            model_app = Application.objects.get(id=static_app.id)
            eq_(unicode(model_app), unicode(static_app.pretty))


class TestViews(amo.tests.TestCase):
    fixtures = ['base/appversion']

    def test_appversions(self):
        eq_(self.client.get(url('apps.appversions')).status_code, 200)

    def test_appversions_feed(self):
        eq_(self.client.get(url('apps.appversions.rss')).status_code, 200)


class TestCommands(amo.tests.TestCase):
    fixtures = ['applications/all_apps.json', 'base/appversion']

    def test_dump_apps(self):
        call_command('dump_apps')
        with open(dump_apps.Command.JSON_PATH, 'r') as f:
            apps = json.load(f)
        db_apps = Application.objects.all()
        assert len(db_apps)
        for app in db_apps:
            data = apps[str(app.id)]
            versions = sorted([a.version for a in
                               AppVersion.objects.filter(application=app)])
            r_app = amo.APPS_ALL[app.id]
            eq_("%s: %r" % (r_app.short, sorted(data['versions'])),
                "%s: %r" % (r_app.short, versions))
            eq_(data['name'], r_app.short)
            eq_(data['guid'], app.guid)
