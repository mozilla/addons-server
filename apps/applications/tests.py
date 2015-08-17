import json
import tempfile

from django.core.management import call_command
from django.db import IntegrityError
from nose.tools import eq_

import amo
import amo.tests
from amo.helpers import url
from applications.models import AppVersion


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

    def test_unique_together_application_version(self):
        """Check that one can't add duplicate application-version pairs."""
        AppVersion.objects.create(application=1, version='123')

        with self.assertRaises(IntegrityError):
            AppVersion.objects.create(application=1, version='123')


class TestViews(amo.tests.TestCase):
    fixtures = ['base/appversion']

    def test_appversions(self):
        eq_(self.client.get(url('apps.appversions')).status_code, 200)

    def test_appversions_feed(self):
        eq_(self.client.get(url('apps.appversions.rss')).status_code, 200)

    def test_appversions_json(self):
        eq_(self.client.get(url('apps.appversions.json')).status_code, 200)


class TestCommands(amo.tests.TestCase):
    fixtures = ['base/appversion']

    def test_dump_apps(self):
        tmpdir = tempfile.mkdtemp()
        with self.settings(MEDIA_ROOT=tmpdir):  # Don't overwrite apps.json.
            from applications.management.commands import dump_apps
            call_command('dump_apps')
            with open(dump_apps.Command.JSON_PATH, 'r') as f:
                apps = json.load(f)
            for idx, app in amo.APP_IDS.iteritems():
                data = apps[str(app.id)]
                versions = sorted([a.version for a in
                                   AppVersion.objects.filter(
                                       application=app.id)])
                eq_("%s: %r" % (app.short, sorted(data['versions'])),
                    "%s: %r" % (app.short, versions))
                eq_(data['name'], app.short)
                eq_(data['guid'], app.guid)

    def test_addnewversion(self):
        new_version = '123.456'
        eq_(len(AppVersion.objects.filter(application=amo.FIREFOX.id,
                                          version=new_version)), 0)

        call_command('addnewversion', 'firefox', new_version)

        eq_(len(AppVersion.objects.filter(application=amo.FIREFOX.id,
                                          version=new_version)),
            1)
