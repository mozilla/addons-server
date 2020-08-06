from django.core.management import call_command
from django.db import IntegrityError

from unittest import mock

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import url
from olympia.amo.tests import APITestClient, reverse_ns, TestCase, user_factory
from olympia.api.tests.utils import APIKeyAuthTestMixin
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


class TestAppVersionsAPI(APIKeyAuthTestMixin, TestCase):
    def setUp(self):
        self.url = reverse_ns(
            'appversions',
            kwargs={'application': 'firefox', 'version': '42.0'})
        self.create_api_user()
        self.grant_permission(self.user, 'AppVersions:Create')

    def test_not_authenticated(self):
        # Don't use self.put() here, it automatically adds authentication.
        response = self.client.put(self.url)
        assert response.status_code == 401
        assert not AppVersion.objects.exists()

    def test_appversions_api_no_permission(self):
        self.user.groups.all().delete()
        response = self.put(self.url)
        assert response.status_code == 403
        assert not AppVersion.objects.exists()

    def test_appversions_api_wrong_verb(self):
        # We could need other verbs in the future, but those are not
        # implemented for the moment.
        response = self.post(self.url)
        assert response.status_code == 405

        response = self.get(self.url)
        assert response.status_code == 405

        response = self.head(self.url)
        assert response.status_code == 405

        response = self.delete(self.url)
        assert response.status_code == 405

        assert not AppVersion.objects.exists()

    def test_invalid_version_argument(self):
        self.url = reverse_ns(
            'appversions',
            kwargs={'application': 'firefox', 'version': 'blah'})
        response = self.put(self.url)
        assert response.status_code == 400
        assert not AppVersion.objects.exists()

    def test_invalid_application_argument(self):
        self.url = reverse_ns(
            'appversions',
            kwargs={'application': 'unknown', 'version': 'blah'})
        response = self.put(self.url)
        assert response.status_code == 400
        assert not AppVersion.objects.exists()

    def test_release(self):
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 2
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*').exists()

    def test_release_android(self):
        self.url = reverse_ns(
            'appversions',
            kwargs={'application': 'android', 'version': '84.0'})
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 2
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='84.0').exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='84.*').exists()

    def test_alpha(self):
        self.url = reverse_ns(
            'appversions',
            kwargs={'application': 'firefox', 'version': '42.0a1'})
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 3
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0a1').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*').exists()

    def test_alpha_already_exists(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.0a1')
        self.url = reverse_ns(
            'appversions',
            kwargs={'application': 'firefox', 'version': '42.0a1'})
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 3
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0a1').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*').exists()

    def test_alpha_release_already_exists(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.0')
        self.url = reverse_ns(
            'appversions',
            kwargs={'application': 'firefox', 'version': '42.0a1'})
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 3
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0a1').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*').exists()

    def test_alpha_star_already_exists(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.*')
        self.url = reverse_ns(
            'appversions',
            kwargs={'application': 'firefox', 'version': '42.0a1'})
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 3
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0a1').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*').exists()

    def test_everything_already_exists(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.0')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.*')
        response = self.put(self.url)
        assert response.status_code == 202
        assert AppVersion.objects.count() == 2
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*').exists()

    def test_alpha_and_star_when_minor_is_not_0(self):
        self.url = reverse_ns(
            'appversions',
            kwargs={'application': 'firefox', 'version': '42.1a2'})
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 3
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.1').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.1a2').exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*').exists()


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
