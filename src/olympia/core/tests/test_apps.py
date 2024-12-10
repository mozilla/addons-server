import os
from unittest import mock

from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import TestCase
from django.test.utils import override_settings


class SystemCheckIntegrationTest(TestCase):
    @override_settings(OLYMPIA_MOUNT='production', HOST_UID='9500')
    def test_unexpected_data_olympia_directory_uid_check(self):
        """
        Check that the /data/olympia directory is owned by the expected uid.
        """
        original_stat = os.stat

        def mock_stat(path, *args, **kwargs):
            if path == '/data/olympia':
                return mock.Mock(st_uid=1000)
            return original_stat(path)

        with mock.patch('olympia.core.apps.os.stat', side_effect=mock_stat):
            with self.assertRaisesMessage(
                SystemCheckError,
                'Expected /data/olympia directory to be owned by 9500, received 1000',
            ):
                call_command('check')

    def test_illegal_host_files_exists_check(self):
        """
        In production, or when the host mount is set to production, we expect
        not to find docker ignored files like Makefile-os in the file system.
        """
        original_exists = os.path.exists

        def mock_exists(path):
            if path == '/data/olympia/Makefile-os':
                return True
            return original_exists(path)

        for host_mount in (None, 'production'):
            with self.subTest(host_mount=host_mount):
                with override_settings(OLYMPIA_MOUNT=host_mount, HOST_UID=9500):
                    with mock.patch(
                        'olympia.core.apps.os.path.exists', side_effect=mock_exists
                    ):
                        with self.assertRaisesMessage(
                            SystemCheckError,
                            'Makefile-os should be excluded by '
                            'dockerignore in production images',
                        ):
                            call_command('check')

    @mock.patch('olympia.core.apps.os.getuid')
    def test_illegal_override_uid_check(self, mock_getuid):
        """
        If the HOST_UID is not set or if it is not set to the
        olympia user actual uid, then file ownership is probably
        incorrect and we should fail the check.
        """
        dummy_uid = '1000'
        olympia_uid = '9500'
        for host_uid in [None, olympia_uid]:
            with override_settings(HOST_UID=host_uid):
                with self.subTest(host_uid=host_uid):
                    mock_getuid.return_value = int(dummy_uid)
                    with self.assertRaisesMessage(
                        SystemCheckError,
                        f'Expected user uid to be {olympia_uid}, received {dummy_uid}',
                    ):
                        call_command('check')

        with override_settings(HOST_UID=dummy_uid, OLYMPIA_MOUNT='development'):
            mock_getuid.return_value = int(olympia_uid)
            with self.assertRaisesMessage(
                SystemCheckError,
                f'Expected user uid to be {dummy_uid}, received {olympia_uid}',
            ):
                call_command('check')

    @mock.patch('olympia.core.apps.connection.cursor')
    def test_db_charset_check(self, mock_cursor):
        mock_cursor.return_value.__enter__.return_value.fetchone.return_value = (
            'character_set_database',
            'utf8mb3',
        )
        with self.assertRaisesMessage(
            SystemCheckError,
            'Database charset invalid. Expected utf8mb4, recieved utf8mb3',
        ):
            call_command('check')

    def test_uwsgi_check(self):
        call_command('check')

        with mock.patch('olympia.core.apps.subprocess') as subprocess:
            subprocess.run.return_value.returncode = 127
            with self.assertRaisesMessage(
                SystemCheckError, 'uwsgi --version returned a non-zero value'
            ):
                call_command('check')

    def test_version_missing_key(self):
        call_command('check')

        with mock.patch('olympia.core.apps.get_version_json') as get_version_json:
            keys = ['version', 'build', 'commit', 'source']
            version_mock = {key: 'test' for key in keys}

            for key in keys:
                version = version_mock.copy()
                version.pop(key)
                get_version_json.return_value = version

                with self.assertRaisesMessage(
                    SystemCheckError, f'{key} is missing from version.json'
                ):
                    call_command('check')

    def test_version_missing_multiple_keys(self):
        call_command('check')

        with mock.patch('olympia.core.apps.get_version_json') as get_version_json:
            get_version_json.return_value = {'version': 'test', 'build': 'test'}
            with self.assertRaisesMessage(
                SystemCheckError, 'commit, source is missing from version.json'
            ):
                call_command('check')
