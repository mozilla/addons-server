import json
from unittest import mock

from datetime import datetime, timedelta
from email import utils

from django.conf import settings
from django.db import connection
from django.test.testcases import TransactionTestCase

from services import update

from olympia import amo
from olympia.addons.models import Addon
from olympia.amo.tests import addon_factory, TestCase
from olympia.applications.models import AppVersion
from olympia.files.models import File
from olympia.versions.models import ApplicationsVersions, Version


class VersionCheckMixin:
    def get_update_instance(self, data):
        instance = update.Update(data)
        instance.cursor = connection.cursor()
        return instance


class TestDataValidate(VersionCheckMixin, TestCase):
    fixtures = ['base/addon_3615', 'base/appversion']

    def setUp(self):
        super().setUp()
        self.data = {
            'id': '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}',
            'version': '2.0.58',
            'reqVersion': 1,
            'appID': '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}',
            'appVersion': '3.7a1pre',
        }

    def test_app_version_fails(self):
        data = self.data.copy()
        del data['appID']
        instance = self.get_update_instance(data)
        assert not instance.is_valid()

    def test_app_version_wrong(self):
        data = self.data.copy()
        data['appVersion'] = '67.7'
        instance = self.get_update_instance(data)
        # If you pass through the wrong version that's fine
        # you will just end up with no updates because your
        # version_int will be out.
        assert instance.is_valid()

    def test_app_version(self):
        data = self.data.copy()
        instance = self.get_update_instance(data)
        assert instance.is_valid()
        assert instance.data['version_int'] == 3070000001000

    def test_sql_injection(self):
        data = self.data.copy()
        data['id'] = "'"
        instance = self.get_update_instance(data)
        assert not instance.is_valid()

    def test_inactive(self):
        addon = Addon.objects.get(pk=3615)
        addon.update(disabled_by_user=True)

        instance = self.get_update_instance(self.data)
        assert not instance.is_valid()

    def test_soft_deleted(self):
        addon = Addon.objects.get(pk=3615)
        addon.update(status=amo.STATUS_DELETED)

        instance = self.get_update_instance(self.data)
        assert not instance.is_valid()

    def test_disabled(self):
        addon = Addon.objects.get(pk=3615)
        addon.update(status=amo.STATUS_DISABLED)

        instance = self.get_update_instance(self.data)
        assert not instance.is_valid()

    def test_no_version(self):
        data = self.data.copy()
        del data['version']
        instance = self.get_update_instance(data)
        assert instance.is_valid()

    def test_unlisted_addon(self):
        """Add-ons with only unlisted versions are valid, they just don't
        receive any updates (See TestLookinstance.test_no_unlisted below)."""
        addon = Addon.objects.get(pk=3615)
        self.make_addon_unlisted(addon)

        instance = self.get_update_instance(self.data)
        assert instance.is_valid()


class TestLookup(VersionCheckMixin, TestCase):
    fixtures = ['addons/update', 'base/appversion']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(id=1865)
        self.platform = None
        self.version_int = 3069900200100

        self.app = amo.APP_IDS[1]
        self.version_1_0_2 = 66463
        self.version_1_1_3 = 90149
        self.version_1_2_0 = 105387
        self.version_1_2_1 = 112396
        self.version_1_2_2 = 115509

    def get_update_instance(self, *args):
        data = {
            'id': self.addon.guid,
            'appID': args[2].guid,
            'appVersion': 1,  # this is going to be overridden
            'appOS': args[3] if args[3] else '',
            'reqVersion': '',
        }
        # Allow version to be optional.
        if args[0]:
            data['version'] = args[0]
        instance = super().get_update_instance(data)
        assert instance.is_valid()
        instance.data['version_int'] = args[1]
        instance.get_update()
        return (
            instance.data['row'].get('version_id'),
            instance.data['row'].get('file_id'),
        )

    def change_status(self, version, status):
        version = Version.objects.get(pk=version)
        file = version.file
        file.status = status
        file.save()
        return version

    def change_version(self, version, name):
        Version.objects.get(pk=version).update(version=name)

    def test_low_client(self):
        """
        Version 3.0a1 of Firefox is 3000000001100 and version 1.0.2 of the
        add-on is returned.
        """
        version, file = self.get_update_instance(
            '', '3000000001100', self.app, self.platform
        )
        assert version == self.version_1_0_2

    def test_new_client(self):
        """
        Version 3.0.12 of Firefox is 3069900200100 and version 1.2.2 of the
        add-on is returned.
        """
        version, file = self.get_update_instance(
            '', self.version_int, self.app, self.platform
        )
        assert version == self.version_1_2_2

    def test_min_client(self):
        """
        Version 3.7a5pre of Firefox is 3070000005000 and version 1.1.3 of
        the add-on is returned, because all later ones are set to minimum
        version of 3.7a5.
        """
        for version in Version.objects.filter(pk__gte=self.version_1_2_0):
            appversion = version.apps.all()[0]
            appversion.min = AppVersion.objects.get(pk=325)  # 3.7a5
            appversion.save()

        version, file = self.get_update_instance(
            '', '3070000005000', self.app, self.platform
        )  # 3.7a5pre
        assert version == self.version_1_1_3

    def test_new_client_ordering(self):
        """
        Given the following:
        * Version 15 (1 day old), max application_version 3.6*
        * Version 12 (1 month old), max application_version 3.7a
        We want version 15, even though version 12 is for a higher version.
        This was found in https://bugzilla.mozilla.org/show_bug.cgi?id=615641.
        """
        application_version = ApplicationsVersions.objects.get(pk=77550)
        application_version.max_id = 350
        application_version.save()

        # Version 1.2.2 is now a lower max version.
        application_version = ApplicationsVersions.objects.get(pk=88490)
        application_version.max_id = 329
        application_version.save()

        version, file = self.get_update_instance(
            '', self.version_int, self.app, self.platform
        )
        assert version == self.version_1_2_2

    def test_public(self):
        """
        If the addon status is public then you get a public version.
        """
        self.change_status(self.version_1_2_2, amo.STATUS_AWAITING_REVIEW)
        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        version, file = self.get_update_instance(
            '1.2', self.version_int, self.app, self.platform
        )
        assert version == self.version_1_2_1

    def test_no_unlisted(self):
        """
        Unlisted versions are always ignored, never served as updates.
        """
        Version.objects.get(pk=self.version_1_2_2).update(
            channel=amo.RELEASE_CHANNEL_UNLISTED
        )
        self.addon.reload()
        assert self.addon.status == amo.STATUS_APPROVED
        version, file = self.get_update_instance(
            '1.2', self.version_int, self.app, self.platform
        )
        assert version == self.version_1_2_1

    def test_can_downgrade(self):
        """
        Check that we can downgrade, if 1.2.0 gets admin disabled
        and the oldest public version is now 1.1.3.
        """
        self.change_status(self.version_1_2_0, amo.STATUS_AWAITING_REVIEW)
        for v in Version.objects.filter(pk__gte=self.version_1_2_1):
            v.delete()
        version, file = self.get_update_instance(
            '1.2', self.version_int, self.app, self.platform
        )

        assert version == self.version_1_1_3

    def test_public_pending_exists(self):
        """
        If the addon status is public and you are asking
        for a beta version we look up a version based on the
        file version at that point. In this case, because the
        file is pending, we are looking for something public.
        """
        self.change_status(self.version_1_2_2, amo.STATUS_AWAITING_REVIEW)
        self.change_status(self.version_1_2_0, amo.STATUS_AWAITING_REVIEW)
        self.change_version(self.version_1_2_0, '1.2beta')

        version, file = self.get_update_instance(
            '1.2', self.version_int, self.app, self.platform
        )

        assert version == self.version_1_2_1

    def test_not_public(self):
        """
        If the addon status is not public, then the update only
        looks for files within that one version.
        """
        self.change_status(self.version_1_2_2, amo.STATUS_NULL)
        self.addon.update(status=amo.STATUS_NULL)
        version, file = self.get_update_instance(
            '1.2.1', self.version_int, self.app, self.platform
        )
        assert version == self.version_1_2_1

    def test_platform_ignore(self):
        """Ignore platform passed by clients (all add-ons are now compatible
        with all platforms, only the app matters)"""
        version = Version.objects.get(pk=115509)
        version, file = self.get_update_instance(
            '1.2', self.version_int, self.app, 'Linux'
        )
        assert version == self.version_1_2_2


class TestDefaultToCompat(VersionCheckMixin, TestCase):
    """
    Test default to compatible with all the various combinations of input.
    """

    fixtures = ['addons/default-to-compat']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(id=337203)
        self.platform = None
        self.app = amo.APP_IDS[1]
        self.app_version_int_4_0 = 4000000200100
        self.app_version_int_5_0 = 5000000200100
        self.app_version_int_6_0 = 6000000200100
        self.app_version_int_7_0 = 7000000200100
        self.app_version_int_8_0 = 8000000200100
        self.ver_1_0 = 1268881
        self.ver_1_1 = 1268882
        self.ver_1_2 = 1268883
        self.ver_1_3 = 1268884

        self.expected = {
            '4.0-strict': self.ver_1_0,
            '4.0-normal': self.ver_1_0,
            '4.0-ignore': self.ver_1_0,
            '5.0-strict': self.ver_1_2,
            '5.0-normal': self.ver_1_2,
            '5.0-ignore': self.ver_1_2,
            '6.0-strict': self.ver_1_3,
            '6.0-normal': self.ver_1_3,
            '6.0-ignore': self.ver_1_3,
            '7.0-strict': self.ver_1_3,
            '7.0-normal': self.ver_1_3,
            '7.0-ignore': self.ver_1_3,
            '8.0-strict': None,
            '8.0-normal': self.ver_1_3,
            '8.0-ignore': self.ver_1_3,
        }

    def update_files(self, **kw):
        for version in self.addon.versions.all():
            version.file.update(**kw)

    def get_update_instance(self, **kw):
        instance = super().get_update_instance(
            {
                'reqVersion': 1,
                'id': self.addon.guid,
                'version': kw.get('item_version', '1.0'),
                'appID': self.app.guid,
                'appVersion': kw.get('app_version', '3.0'),
            }
        )
        assert instance.is_valid()
        instance.compat_mode = kw.get('compat_mode', 'strict')
        instance.get_update()
        return instance.data['row'].get('version_id')

    def check(self, expected):
        """
        Checks Firefox versions 4.0 to 8.0 in each compat mode and compares it
        to the expected version.
        """
        versions = ['4.0', '5.0', '6.0', '7.0', '8.0']
        modes = ['strict', 'normal', 'ignore']

        for version in versions:
            for mode in modes:
                assert (
                    self.get_update_instance(app_version=version, compat_mode=mode)
                    == expected['-'.join([version, mode])]
                )

    def test_baseline(self):
        # Tests simple add-on (non-strict_compatibility).
        self.check(self.expected)

    def test_strict_opt_in(self):
        # Tests add-on with opt-in strict compatibility
        self.update_files(strict_compatibility=True)
        self.expected.update(
            {
                '8.0-normal': None,
            }
        )
        self.check(self.expected)


class TestResponse(VersionCheckMixin, TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super().setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.data = {
            'id': '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}',
            'version': '2.0.58',
            'reqVersion': 1,
            'appID': '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}',
            'appVersion': '3.7a1pre',
        }

    def test_bad_guid(self):
        self.data['id'] = 'garbage'
        instance = self.get_update_instance(self.data)
        assert json.loads(instance.get_output()) == instance.get_error_output()

    def test_good_version(self):
        instance = self.get_update_instance(self.data)
        instance.is_valid()
        instance.get_update()
        assert instance.data['row']['hash'].startswith('sha256:3808b13e')
        assert instance.data['row']['min'] == '2.0'
        assert instance.data['row']['max'] == '4.0'

    def test_no_app_version(self):
        data = self.data.copy()
        data['appVersion'] = '1.4'
        instance = self.get_update_instance(data)
        instance.is_valid()
        assert not instance.get_update()

    def test_low_app_version(self):
        data = self.data.copy()
        data['appVersion'] = '2.0'
        instance = self.get_update_instance(data)
        instance.is_valid()
        instance.get_update()
        assert instance.data['row']['hash'].startswith('sha256:3808b13e')
        assert instance.data['row']['min'] == '2.0'
        assert instance.data['row']['max'] == '4.0'

    def test_content_type(self):
        instance = self.get_update_instance(self.data)
        ('Content-Type', 'text/xml') in instance.get_headers(1)

    def test_cache_control(self):
        instance = self.get_update_instance(self.data)
        ('Cache-Control', 'public, max-age=3600') in instance.get_headers(1)

    def test_length(self):
        instance = self.get_update_instance(self.data)
        ('Cache-Length', '1') in instance.get_headers(1)

    def test_expires(self):
        """Check there are these headers and that expires is 3600 later."""
        # We aren't bother going to test the actual time in expires, that
        # way lies pain with broken tests later.
        instance = self.get_update_instance(self.data)
        headers = dict(instance.get_headers(1))
        last_modified = datetime(*utils.parsedate_tz(headers['Last-Modified'])[:7])
        expires = datetime(*utils.parsedate_tz(headers['Expires'])[:7])
        assert (expires - last_modified).seconds == 3600

    def get_file_url(self):
        """Return the file url with the hash as parameter."""
        return self.addon.current_version.file.get_absolute_url()

    def test_url(self):
        instance = self.get_update_instance(self.data)
        content = instance.get_output()
        data = json.loads(content)
        guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        assert data['addons'][guid]['updates'][0]['update_link'] == self.get_file_url()

    def test_url_new_directory_structure(self):
        File.objects.filter(pk=self.addon.current_version.file.pk).update(
            file='67/4567/1234567/addon-1.0.xpi'
        )
        self.addon.current_version.file.reload()
        self.test_url()

    def test_url_local_recent(self):
        a_bit_ago = datetime.now() - timedelta(seconds=60)
        File.objects.get(pk=67442).update(datestatuschanged=a_bit_ago)
        instance = self.get_update_instance(self.data)
        content = instance.get_output()
        data = json.loads(content)
        guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        assert data['addons'][guid]['updates'][0]['update_link'] == self.get_file_url()

    def test_hash(self):
        content = self.get_update_instance(self.data).get_output()
        data = json.loads(content)

        file = File.objects.get(pk=67442)
        guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        assert data['addons'][guid]['updates'][0]['update_hash'] == file.hash

        file = File.objects.get(pk=67442)
        file.hash = ''
        file.save()

        content = self.get_update_instance(self.data).get_output()
        data = json.loads(content)
        assert 'update_hash' not in data['addons'][guid]['updates'][0]

    def test_release_notes(self):
        content = self.get_update_instance(self.data).get_output()
        data = json.loads(content)
        guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        expected_url = (
            'http://testserver/%APP_LOCALE%/firefox/'
            'addon/a3615/versions/2.1.072/updateinfo/'
        )
        assert data['addons'][guid]['updates'][0]['update_info_url'] == expected_url

        version = Version.objects.get(pk=81551)
        version.update(release_notes=None)

        content = self.get_update_instance(self.data).get_output()
        data = json.loads(content)
        assert 'update_info_url' not in data['addons'][guid]['updates'][0]

    def test_release_notes_android(self):
        # Quick & dirty way to make the add-on compatible with android and
        # force the update request to be from Android as well.
        AppVersion.objects.update(application=amo.ANDROID.id)
        self.data['appID'] = amo.ANDROID.guid

        content = self.get_update_instance(self.data).get_output()
        data = json.loads(content)
        guid = '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}'
        expected_url = (
            'http://testserver/%APP_LOCALE%/android/'
            'addon/a3615/versions/2.1.072/updateinfo/'
        )
        assert data['addons'][guid]['updates'][0]['update_info_url'] == expected_url

    def test_no_updates_at_all(self):
        self.addon.versions.all().delete()
        instance = self.get_update_instance(self.data)
        assert json.loads(instance.get_output()) == instance.get_no_updates_output()

    def test_no_updates_my_fx(self):
        data = self.data.copy()
        data['appVersion'] = '5.0.1'
        instance = self.get_update_instance(data)
        assert json.loads(instance.get_output()) == instance.get_no_updates_output()

    def test_application(self):
        # Basic test making sure application() is returning the output of
        # Update.get_output(). Have to mock Update(): otherwise, even though
        # we're setting SERVICES_DATABASE to point to the test database in
        # settings_test.py, we wouldn't see results because the data wouldn't
        # exist with the cursor the update service is using, which is different
        # from the one used by django tests.
        environ = {'QUERY_STRING': ''}
        self.start_response_call_count = 0

        expected_headers = [('FakeHeader', 'FakeHeaderValue')]

        expected_output = b'{"fake": "output"}'

        def start_response_inspector(status, headers):
            self.start_response_call_count += 1
            assert status == '200 OK'
            assert headers == expected_headers

        with mock.patch('services.update.Update') as UpdateMock:
            update_instance = UpdateMock.return_value
            update_instance.get_headers.return_value = expected_headers
            update_instance.get_output.return_value = expected_output
            output = update.application(environ, start_response_inspector)
        assert self.start_response_call_count == 1
        # Output is an array with a single string containing the body of the
        # response.
        assert output == [expected_output]

    @mock.patch('services.update.logging.config.dictConfig')
    @mock.patch('services.update.Update')
    def test_exception_handling(self, UpdateMock, dictConfigMock):
        """Test ensuring exceptions are raised and logged properly."""

        class CustomException(Exception):
            pass

        self.inspector_call_count = 0
        update_instance = UpdateMock.return_value
        update_instance.get_output.side_effect = CustomException('Boom!')

        def inspector(status, headers):
            self.inspector_call_count += 1

        with self.assertRaises(CustomException):
            with self.assertLogs(level='ERROR') as logs:
                update.application({'QUERY_STRING': ''}, inspector)
        assert self.inspector_call_count == 0
        assert len(logs.records) == 1
        assert logs.records[0].message == 'Boom!'
        assert logs.records[0].exc_info[1] == update_instance.get_output.side_effect

        # Ensure we had set up logging correctly. We can't let the actual call
        # go through, it would override the loggers assertLogs() set up.
        assert dictConfigMock.call_count == 1
        assert dictConfigMock.call_args[0] == (settings.LOGGING,)


# This test needs to be a TransactionTestCase because we want to test the
# behavior of database cursor created by the update service. Since the data is
# written by a different cursor, it needs to be committed for the update
# service to see it (Other tests above that aren't explicitly mocking the
# service and care about the output cheat and override the cursor to use
# django's).
class TestUpdateConnectionEncoding(TransactionTestCase):
    def setUp(self):
        self.addon = addon_factory()

    def test_service_database_setting(self):
        expected_name = settings.DATABASES['default']['NAME']
        assert 'test' in expected_name
        assert settings.SERVICES_DATABASE['NAME'] == expected_name

        connection = update.pool.connect()
        cursor = connection.cursor()
        cursor.execute('SELECT DATABASE();')
        assert cursor.fetchone()[0] == expected_name
        connection.close()

    def test_connection_pool_encoding(self):
        connection = update.pool.connect()
        assert connection.connection.encoding == 'utf8'
        connection.close()

    def test_unicode_data(self):
        # To trigger the error this test is trying to cover, we need 2 things:
        # - An update request that would be considered 'valid', i.e. the
        #   necessary parameters are presentTestUpdateConnectionEncoding and
        #   the add-on exists.
        # - A database cursor instantiated from the update service, not by
        #   django tests.
        # Note that this test would hang before the fix to pass charset when
        # connecting in get_connection().
        data = {
            'id': self.addon.guid,
            'reqVersion': '2鎈',
            'appID': amo.FIREFOX.guid,
            'appVersion': '78.0',
        }
        instance = update.Update(data)
        output = instance.get_output()
        update_data = json.loads(output)
        assert update_data
