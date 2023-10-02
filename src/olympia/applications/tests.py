from django.core.exceptions import BadRequest
from django.core.management import call_command
from django.db import IntegrityError

import responses

from olympia import amo
from olympia.amo.tests import APITestClientSessionID, TestCase, reverse_ns
from olympia.api.tests.utils import APIKeyAuthTestMixin
from olympia.applications.models import AppVersion


class TestAppVersion(TestCase):
    def test_unique_together_application_version(self):
        """Check that one can't add duplicate application-version pairs."""
        AppVersion.objects.all().delete()
        AppVersion.objects.create(application=1, version='123')

        with self.assertRaises(IntegrityError):
            AppVersion.objects.create(application=1, version='123')


class TestViews(TestCase):
    fixtures = ['base/appversion']

    def test_appversions(self):
        response = self.client.get('/en-US/firefox/pages/appversions/')
        self.assert3xx(response, '/api/v5/applications/firefox/', status_code=301)

    def test_appversions_feed(self):
        response = self.client.get('/en-US/firefox/pages/appversions/format:rss')
        self.assert3xx(response, '/api/v5/applications/firefox/', status_code=301)


class TestAppVersionsAPIGet(TestCase):
    client_class = APITestClientSessionID

    def setUp(self):
        self.url = reverse_ns('appversions-list', kwargs={'application': 'firefox'})
        AppVersion.objects.all().delete()

    def test_invalid_application_argument(self):
        url = reverse_ns('appversions-list', kwargs={'application': 'unknown'})
        response = self.client.get(url)
        assert response.status_code == 400

    def test_appversions_api_wrong_verb(self):
        # We could need other verbs in the future, but those are not
        # implemented for the moment.
        response = self.client.post(self.url)
        assert response.status_code == 405

        response = self.client.put(self.url)
        assert response.status_code == 401

        response = self.client.head(self.url)
        assert response.status_code == 405

        response = self.client.delete(self.url)
        assert response.status_code == 405

    def test_response(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='123')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='123.0')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='123.*')
        # Android appversions shouldn't be included in a /firefox/ request
        AppVersion.objects.create(application=amo.ANDROID.id, version='123.1')

        response = self.client.get(self.url)
        assert response.data == {
            'guid': amo.FIREFOX.guid,
            'versions': [
                # Ordered by the version, not by the creation date
                '123',
                '123.0',
                '123.*',
            ],
        }
        assert response.status_code == 200
        # cached for an hour
        assert response['cache-control'] == 'max-age=3600'


class TestAppVersionsAPIPut(APIKeyAuthTestMixin, TestCase):
    def setUp(self):
        self.url = reverse_ns(
            'appversions', kwargs={'application': 'firefox', 'version': '42.0'}
        )
        self.create_api_user()
        self.grant_permission(self.user, 'AppVersions:Create')
        AppVersion.objects.all().delete()

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
        assert response.status_code == 200

        response = self.head(self.url)
        assert response.status_code == 405

        response = self.delete(self.url)
        assert response.status_code == 405

        assert not AppVersion.objects.exists()

    def test_invalid_version_argument(self):
        self.url = reverse_ns(
            'appversions', kwargs={'application': 'firefox', 'version': 'blah'}
        )
        response = self.put(self.url)
        assert response.status_code == 400
        assert not AppVersion.objects.exists()

    def test_invalid_application_argument(self):
        self.url = reverse_ns(
            'appversions', kwargs={'application': 'unknown', 'version': 'blah'}
        )
        response = self.put(self.url)
        assert response.status_code == 400
        assert not AppVersion.objects.exists()

    def test_release(self):
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 4
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.*'
        ).exists()

    def test_release_android(self):
        self.url = reverse_ns(
            'appversions', kwargs={'application': 'android', 'version': '84.0'}
        )
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 4
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='84.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='84.*'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='84.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='84.*'
        ).exists()

    def test_alpha(self):
        self.url = reverse_ns(
            'appversions', kwargs={'application': 'firefox', 'version': '42.0a1'}
        )
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 6
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0a1'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0a1'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.*'
        ).exists()

    def test_alpha_already_exists_for_one_app(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.0a1')
        self.url = reverse_ns(
            'appversions', kwargs={'application': 'firefox', 'version': '42.0a1'}
        )
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 6
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0a1'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0a1'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.*'
        ).exists()

    def test_alpha_release_already_exists_for_one_app(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.0')
        self.url = reverse_ns(
            'appversions', kwargs={'application': 'firefox', 'version': '42.0a1'}
        )
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 6
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0a1'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0a1'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.*'
        ).exists()

    def test_alpha_star_already_exists_for_one_app(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.*')
        self.url = reverse_ns(
            'appversions', kwargs={'application': 'firefox', 'version': '42.0a1'}
        )
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 6
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0a1'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0a1'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.*'
        ).exists()

    def test_everything_already_exists_for_one_app(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.0')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.*')
        response = self.put(self.url)
        assert response.status_code == 201  # We created some Android stuff.
        assert AppVersion.objects.count() == 4
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.*'
        ).exists()

    def test_alpha_and_star_when_minor_is_not_0_for_one_app(self):
        self.url = reverse_ns(
            'appversions', kwargs={'application': 'firefox', 'version': '42.1a2'}
        )
        response = self.put(self.url)
        assert response.status_code == 201
        assert AppVersion.objects.count() == 6
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.1'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.1a2'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.1'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.1a2'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.*'
        ).exists()

    def test_everything_already_exists(self):
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.0')
        AppVersion.objects.create(application=amo.FIREFOX.id, version='42.*')
        AppVersion.objects.create(application=amo.ANDROID.id, version='42.0')
        AppVersion.objects.create(application=amo.ANDROID.id, version='42.*')
        response = self.put(self.url)
        assert response.status_code == 202  # Nothing to create at all.
        assert AppVersion.objects.count() == 4
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='42.*'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='42.*'
        ).exists()


class TestCommands(TestCase):
    fixtures = ['base/appversion']

    def test_addnewversion(self):
        new_version = '123.456'
        assert (
            len(
                AppVersion.objects.filter(
                    application=amo.FIREFOX.id, version=new_version
                )
            )
            == 0
        )

        call_command('addnewversion', 'firefox', new_version)

        assert (
            len(
                AppVersion.objects.filter(
                    application=amo.FIREFOX.id, version=new_version
                )
            )
            == 1
        )

    def test_import_prod_versions(self):
        assert not AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='53.0'
        ).exists()
        assert not AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='53.*'
        ).exists()
        assert not AppVersion.objects.filter(
            application=amo.ANDROID.id, version='52.0'
        ).exists()
        assert not AppVersion.objects.filter(
            application=amo.ANDROID.id, version='52.*'
        ).exists()

        responses.add(
            responses.GET,
            'https://addons.mozilla.org/api/v5/applications/firefox/',
            json={'guid': amo.FIREFOX.guid, 'versions': ['53.0', '53.*']},
        )
        responses.add(
            responses.GET,
            'https://addons.mozilla.org/api/v5/applications/android/',
            json={'guid': amo.ANDROID.guid, 'versions': ['52.0', '52.*']},
        )

        call_command('import_prod_versions')

        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='53.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.FIREFOX.id, version='53.*'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='52.0'
        ).exists()
        assert AppVersion.objects.filter(
            application=amo.ANDROID.id, version='52.*'
        ).exists()

    def test_import_prod_versions_failures(self):
        responses.add(
            responses.GET,
            'https://addons.mozilla.org/api/v5/applications/firefox/',
            json={},
            status=404,
        )
        responses.add(
            responses.GET,
            'https://addons.mozilla.org/api/v5/applications/firefox/',
            json={'guid': amo.FIREFOX.guid, 'versions': []},
        )
        responses.add(
            responses.GET,
            'https://addons.mozilla.org/api/v5/applications/firefox/',
            json={'guid': 'not-firefoxs-guid', 'versions': ['52.0', '52.*']},
        )

        with self.assertRaises(BadRequest) as exc:
            call_command('import_prod_versions')
            assert exc.exception.messages == [
                'Importing versions from AMO prod failed: 404.'
            ]
        with self.assertRaises(BadRequest) as exc:
            call_command('import_prod_versions')
            assert exc.exception.messages == [
                'Importing versions from AMO prod failed: guid mistmatch - '
                f'expected={amo.FIREFOX.guid}; got=not-firefoxs-guid.'
            ]

        with self.assertRaises(BadRequest) as exc:
            call_command('import_prod_versions')
            assert exc.exception.messages == [
                'Importing versions from AMO prod failed: no versions.'
            ]

        assert AppVersion.objects.all().exists()
