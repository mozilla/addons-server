from django.core.management import call_command
from django.db import IntegrityError

from unittest import mock

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import url
from olympia.amo.tests import TestCase
from olympia.applications.models import AppVersion


class TestAppVersion(TestCase):

    def test_unique_together_application_version(self):
        """Check that one can't add duplicate application-version pairs."""
        AppVersion.objects.create(application=1, version='123')

        with self.assertRaises(IntegrityError):
            AppVersion.objects.create(application=1, version='123')


class TestViews(TestCase):
    fixtures = ['base/appversion']

    def test_appversions(self):
        assert self.client.get(url('apps.appversions')).status_code == 200

    def test_appversions_feed(self):
        assert self.client.get(url('apps.appversions.rss')).status_code == 200


class TestCommands(TestCase):
    fixtures = ['base/appversion']

    def test_addnewversion(self):
        new_version = '123.456'
        assert len(AppVersion.objects.filter(
            application=amo.FIREFOX.id, version=new_version)) == 0

        call_command('addnewversion', 'firefox', new_version)

        assert len(AppVersion.objects.filter(
            application=amo.FIREFOX.id, version=new_version)) == 1

    @mock.patch('olympia.applications.management.commands.import_prod_versions'
                '.PyQuery', spec=True)
    def test_import_prod_versions(self, pyquery_mock):
        assert not AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='53.0').exists()
        assert not AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='53.*').exists()

        # Result of PyQuery()
        MockedDoc = mock.Mock()
        pyquery_mock.return_value = MockedDoc

        # Result of PyQuery()('selector'). Return 2 applications, one with a
        # valid guid and one that is garbage and should be ignored.
        MockedDocResult = [
            mock.Mock(spec=[], text='lol'),
            mock.Mock(spec=[], text='some versions...'),
            mock.Mock(spec=[], text='{ec8030f7-c20a-464f-9b0e-13a3a9e97384}'),
            mock.Mock(spec=[], text='53.0, 53.*'),
        ]
        MockedDoc.return_value = MockedDocResult

        call_command('import_prod_versions')

        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='53.0').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='53.*').exists()
