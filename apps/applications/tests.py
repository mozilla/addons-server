import json
import tempfile

from django.core.management import call_command
from django.db import IntegrityError

import amo
import amo.tests
from amo.helpers import url
from applications.models import AppVersion
import pytest


class TestAppVersion(amo.tests.TestCase):

    def test_major_minor(self):
        """Check that major/minor/alpha is getting set."""
        v = AppVersion(version='3.0.12b2')
        assert v.major == 3
        assert v.minor1 == 0
        assert v.minor2 == 12
        assert v.minor3 is None
        assert v.alpha == 'b'
        assert v.alpha_ver == 2

        v = AppVersion(version='3.6.1apre2+')
        assert v.major == 3
        assert v.minor1 == 6
        assert v.minor2 == 1
        assert v.alpha == 'a'
        assert v.pre == 'pre'
        assert v.pre_ver == 2

        v = AppVersion(version='')
        assert v.major is None
        assert v.minor1 is None
        assert v.minor2 is None
        assert v.minor3 is None

    def test_unique_together_application_version(self):
        """Check that one can't add duplicate application-version pairs."""
        AppVersion.objects.create(application=1, version='123')

        with pytest.raises(IntegrityError):
            AppVersion.objects.create(application=1, version='123')


class TestViews(amo.tests.TestCase):
    fixtures = ['base/appversion']

    def test_appversions(self):
        assert self.client.get(url('apps.appversions')).status_code == 200

    def test_appversions_feed(self):
        assert self.client.get(url('apps.appversions.rss')).status_code == 200


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
                assert "%s: %r" % (app.short, sorted(data['versions'])) == "%s: %r" % (app.short, versions)
                assert data['name'] == app.short
                assert data['guid'] == app.guid

    def test_addnewversion(self):
        new_version = '123.456'
        assert len(AppVersion.objects.filter(application=amo.FIREFOX.id, version=new_version)) == 0

        call_command('addnewversion', 'firefox', new_version)
        assert len(AppVersion.objects.filter(application=amo.FIREFOX.id, version=new_version)) == 1
