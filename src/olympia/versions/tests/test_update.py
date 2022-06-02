from urllib.parse import quote

from django.conf import settings
from django.urls import reverse

import pytest

from olympia import amo
from olympia.amo.tests import addon_factory, TestCase, version_factory
from olympia.constants.applications import APP_GUIDS
from olympia.versions.models import ApplicationsVersions, AppVersion


class TestUpdate(TestCase):
    def setUp(self):
        self.addon = addon_factory(
            version_kw={
                'min_app_version': '57.0',
                'max_app_version': '*',
                'version': '1.0',
            },
            file_kw={'hash': 'fakehash'},
        )
        self.addon.current_version.update(created=self.days_ago(42))
        self.url = reverse('addons.versions.update')
        self.query_params = {
            'id': self.addon.guid,
            'appID': amo.FIREFOX.guid,
            'appVersion': '99.0',
        }

    def _check_common_headers(self, response):
        assert response['Content-Type'] == 'application/json'
        assert response['Cache-Control'] == 'max-age=3600'
        assert response['ETag']
        assert response['Content-Length']

    def _check_ok(self, expected_version):
        with self.assertNumQueries(2):
            # - One query to validate the add-on
            # - One query to fetch the update
            response = self.client.get(self.url, self.query_params)
        assert response.status_code == 200
        self._check_common_headers(response)
        data = response.json()
        assert len(data['addons'][self.addon.guid]['updates'])
        update_data = response.json()['addons'][self.addon.guid]['updates'][0]
        assert update_data['version'] == expected_version.version
        app = APP_GUIDS[self.query_params['appID']]
        assert (
            update_data['applications']['gecko']['strict_min_version']
            == expected_version.compatible_apps[app].min.version
        )
        if expected_version.file.strict_compatibility:
            assert (
                update_data['applications']['gecko']['strict_max_version']
                == expected_version.compatible_apps[app].max.version
            )
        assert update_data['update_hash'] == expected_version.file.hash
        assert update_data['update_link'] == (
            f'{settings.SITE_URL}/{app.short}/'
            f'downloads/file/{expected_version.file.pk}/'
            f'{expected_version.file.pretty_filename}'
        )
        if expected_version.release_notes:
            assert update_data['update_info_url'] == (
                f'{settings.SITE_URL}/%APP_LOCALE%/{app.short}'
                f'/addon/{quote(self.addon.slug)}/versions/'
                f'{expected_version.version}/updateinfo/'
            )

    def _check_invalid(self, expected_status_code=400):
        if expected_status_code == 400:
            # Request is invalid, we shouldn't use the database.
            expected_num_queries = 0
        else:
            # If we're expected something else than a 400, it means the request
            # itself was valid and we had to go to the database to return an
            # empty response because the add-on itself was invalid.
            expected_num_queries = 1
        with self.assertNumQueries(expected_num_queries):
            response = self.client.get(self.url, self.query_params)
        assert response.status_code == expected_status_code
        self._check_common_headers(response)
        assert response.json() == {}

    def _check_no_updates(self):
        with self.assertNumQueries(2):
            # - One query to validate the add-on
            # - One query to fetch the update (which will return nothing)
            response = self.client.get(self.url, self.query_params)
        assert response.status_code == 200
        self._check_common_headers(response)
        assert response.json() == {'addons': {self.addon.guid: {'updates': []}}}

    def test_reverse_no_app_or_locale(self):
        assert self.url == '/update/'

    def test_no_app_id(self):
        self.query_params.pop('appID')
        self._check_invalid()

    def test_no_appversion(self):
        self.query_params.pop('appVersion')
        self._check_invalid()

    def test_invalid_app_id(self):
        self.query_params['appID'] = 'garbag2鎈'
        self._check_invalid()

    def test_unknown_addon(self):
        self.query_params['id'] = 'unknowné鎈'
        self._check_invalid(expected_status_code=200)

    def test_inactive_addon(self):
        self.addon.update(disabled_by_user=True)
        self._check_invalid(expected_status_code=200)

    def test_deleted_addon(self):
        self.addon.delete()
        self._check_invalid(expected_status_code=200)

    def test_disabled_addon(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        self._check_invalid(expected_status_code=200)

    def test_no_versions(self):
        self.addon.versions.all().delete()
        self._check_no_updates()

    def test_no_updates_because_minimum_appversion_too_low(self):
        self.query_params['appVersion'] = '56.0'
        self._check_no_updates()

    def test_basic(self):
        expected_version = version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='*',
            version='1.1',
            file_kw={'hash': 'fakehash1.1', 'filename': 'webextension_no_id.zip'},
        )
        self._check_ok(expected_version)

    def test_release_notes(self):
        self.addon.current_version.release_notes = 'Some release notes'
        self.addon.current_version.save()
        self._check_ok(self.addon.current_version)

    def test_android_with_release_notes(self):
        self.query_params['appID'] = amo.ANDROID.guid
        self.addon.current_version.apps.all().update(application=amo.ANDROID.id)
        expected_version = version_factory(
            addon=self.addon,
            application=amo.ANDROID.id,
            min_app_version='58.0',
            max_app_version='*',
            version='1.1',
            file_kw={'hash': 'fakehash1.1'},
            release_notes='Some release notes',
        )
        self._check_ok(expected_version)

    def test_android_compatible_with_both_android_and_firefox_on_same_version(self):
        self.query_params['appID'] = amo.ANDROID.guid
        av_min, _ = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='57.0'
        )
        av_max, _ = AppVersion.objects.get_or_create(
            application=amo.ANDROID.id, version='*'
        )
        ApplicationsVersions.objects.get_or_create(
            application=amo.ANDROID.id,
            version=self.addon.current_version,
            min=av_min,
            max=av_max,
        )
        expected_version = version_factory(
            addon=self.addon,
            application=amo.ANDROID.id,
            min_app_version='58.0',
            max_app_version='*',
            version='1.1',
            file_kw={'hash': 'fakehash1.1', 'filename': 'webextension_no_id.zip'},
            release_notes='Some release notes',
        )
        self._check_ok(expected_version)

    def test_basic_max_star(self):
        expected_version = version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='*',
            version='1.1',
            file_kw={'hash': 'fakehash1.1'},
        )
        self._check_ok(expected_version)

    def test_new_style_guid(self):
        self.addon.update(guid='myaddon@')
        self.query_params['id'] = 'myaddon@'
        self._check_ok(self.addon.current_version)

    def test_min_appversion_low(self):
        expected_version = self.addon.current_version
        version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='*',
            version='1.1',
            file_kw={'hash': 'fakehash1.1'},
        )
        self.query_params['appVersion'] = '57.0'
        # We're requesting a version compatible with 57.0, so the newly added
        # version won't do it. We should be served the older version instead.
        self._check_ok(expected_version)

    def test_latest_version_is_for_another_app_only(self):
        expected_version = self.addon.current_version
        version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='*',
            application=amo.ANDROID.id,
            version='1.1',
            file_kw={'hash': 'fakehash1.1'},
        )
        self._check_ok(expected_version)

    def test_newer_version_not_compatible_because_of_strict_compatibility(self):
        expected_version = self.addon.current_version
        version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='58.*',
            version='1.1',
            file_kw={'strict_compatibility': True, 'hash': 'fakehash11'},
        )
        # The newer version has strict compatibility set to 58.* max so it
        # won't be picked up as we're on a higher version.
        self._check_ok(expected_version)

    def test_newer_version_not_public(self):
        expected_version = self.addon.current_version
        version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='*',
            version='1.1',
            file_kw={'status': amo.STATUS_AWAITING_REVIEW, 'hash': 'fakehash11'},
        )
        # The newer version is not approved, so it won't be picked up.
        self._check_ok(expected_version)

    def test_newer_version_disabled(self):
        expected_version = self.addon.current_version
        version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='*',
            version='1.1',
            file_kw={'status': amo.STATUS_DISABLED, 'hash': 'fakehash11'},
        )
        # The newer version is disabled, so it won't be picked up.
        self._check_ok(expected_version)

    def test_no_unlisted_version(self):
        expected_version = self.addon.current_version
        version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='*',
            version='1.1',
            channel=amo.RELEASE_CHANNEL_UNLISTED,
            file_kw={'hash': 'fakehash1.1'},
        )
        # The newer version is unlisted, so it won't be picked up.
        self._check_ok(expected_version)

    def test_no_deleted_version(self):
        expected_version = self.addon.current_version
        version = version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='*',
            version='1.1',
            file_kw={'hash': 'fakehash1.1'},
        )
        version.delete()
        # The newer version is deleted, so it won't be picked up.
        self._check_ok(expected_version)

    def test_different_addon(self):
        expected_version = self.addon.current_version
        addon_factory(
            version_kw={
                'min_app_version': '57.0',
                'max_app_version': '*',
                'version': '1.1',
            },
            file_kw={'hash': 'fakehash1.1'},
        )
        # The newer version is for a different add-on so it won't be picked up.
        self._check_ok(expected_version)

    def test_no_compat_addon(self):
        # No updates will be found for add-ons with no compat in default
        # (strict) mode.
        self.addon.current_version.apps.all().delete()
        self._check_no_updates()

    def test_ignore_mode(self):
        self.query_params['compatMode'] = 'ignore'
        self.test_basic()

    def test_ignore_mode_strict_compatibility_version(self):
        self.query_params['compatMode'] = 'ignore'
        expected_version = version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='58.*',
            version='1.1',
            file_kw={'strict_compatibility': True, 'hash': 'fakehash11'},
        )
        # Despite having strict compatibility set to 58.* max, the newer
        # version _will_ get picked up as we're in ignore mode.
        self._check_ok(expected_version)

    @pytest.mark.xfail(reason='Need to sort out compatibility info for dictionaries')
    def test_ignore_mode_no_compat_addon(self):
        self.query_params['compatMode'] = 'ignore'
        self.addon.current_version.apps.all().delete()
        # FIXME: this doesn't work, because the update service is always
        # passing the minimum app version, and we just deleted it...
        # Investigate what should happen here, because that's not new behavior:
        # the old service did that too. So should add-ons marked as having no
        # compatibility, like dictionaries, always have one recorded in the db
        # anyway ? It seems like they do in production.
        self._check_ok(self.addon.current_version)

    def test_normal_mode(self):
        self.query_params['compatMode'] = 'normal'
        self.test_basic()

    def test_normal_mode_min_appversion_low(self):
        self.query_params['compatMode'] = 'normal'
        self.test_min_appversion_low()

    def test_normal_mode_strict_compatibility_version(self):
        self.query_params['compatMode'] = 'normal'
        self.test_newer_version_not_compatible_because_of_strict_compatibility()

    def test_normal_mode_no_compat_addon(self):
        # No updates will be found for add-ons with no compat in normal
        # mode.
        self.query_params['compatMode'] = 'normal'
        self.addon.current_version.apps.all().delete()
        self._check_no_updates()
