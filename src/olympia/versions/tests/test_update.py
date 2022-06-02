from django.urls import reverse

from olympia import amo
from olympia.amo.tests import addon_factory, TestCase, version_factory


class TestUpdate(TestCase):
    def setUp(self):
        self.addon = addon_factory(
            version_kw={
                'min_app_version': '57.0',
                'max_app_version': '*',
                'version': '1.0',
            }
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
        response = self.client.get(self.url, self.query_params)
        assert response.status_code == 200
        self._check_common_headers(response)
        data = response.json()
        assert len(data['addons'][self.addon.guid]['updates'])
        update_data = response.json()['addons'][self.addon.guid]['updates'][0]
        assert update_data['version'] == expected_version.version
        # FIXME
        # - update link (ensuring app and filename, no locale)
        # - applications / gecko / strict min version
        # - applications / gecko / strict_max_version if strict_compatibility
        # - update_hash
        # - update_info_url (ensuring app, but also locale is APP_LOCALE)
        pass

    def _check_invalid(self, expected_status_code=400):
        response = self.client.get(self.url, self.query_params)
        assert response.status_code == expected_status_code
        self._check_common_headers(response)
        assert response.json() == {}

    def _check_empty(self):
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
        self._check_empty()

    def test_no_updates_because_minimum_appversion_too_low(self):
        self.query_params['appVersion'] = '56.0'
        self._check_empty()

    def test_basic(self):
        expected_version = version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='*',
            version='1.1',
        )
        self._check_ok(expected_version)

    def test_basic_max_star(self):
        expected_version = version_factory(
            addon=self.addon, min_app_version='58.0', max_app_version='*', version='1.1'
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
        )
        self.query_params['appVersion'] = '57.0'
        # We're requesting a version compatible with 57.0, so the newly added
        # version won't do it. We should be served the older version instead.
        self._check_ok(expected_version)
        pass

    def test_latest_version_is_for_another_app_only(self):
        expected_version = self.addon.current_version
        version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='*',
            application=amo.ANDROID.id,
            version='1.1',
        )
        self._check_ok(expected_version)

    def test_newer_version_not_compatible_because_of_strict_compatibility(self):
        expected_version = self.addon.current_version
        version_factory(
            addon=self.addon,
            min_app_version='58.0',
            max_app_version='58.*',
            version='1.1',
            file_kw={'strict_compatibility': True},
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
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
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
            file_kw={'status': amo.STATUS_DISABLED},
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
            }
        )
        # The newer version is for a different add-on so it won't be picked up.
        self._check_ok(expected_version)

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
            file_kw={'strict_compatibility': True},
        )
        # Despite having strict compatibility set to 58.* max, the newer
        # version _will_ get picked up as we're in ignore mode.
        self._check_ok(expected_version)

    def test_normal_mode(self):
        self.query_params['compatMode'] = 'normal'
        self.test_basic()

    def test_normal_mode_min_appversion_low(self):
        self.query_params['compatMode'] = 'normal'
        self.test_min_appversion_low()

    def test_normal_mode_strict_compatibility_version(self):
        self.query_params['compatMode'] = 'normal'
        self.test_newer_version_not_compatible_because_of_strict_compatibility()
