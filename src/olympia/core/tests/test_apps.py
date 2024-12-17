from unittest import mock

from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import TestCase

from olympia.core.utils import REQUIRED_VERSION_KEYS


class SystemCheckIntegrationTest(TestCase):
    def setUp(self):
        self.default_version_json = {
            'tag': 'mozilla/addons-server:1.0',
            'target': 'production',
            'commit': 'abc',
            'version': '1.0',
            'build': 'http://example.com/build',
            'source': 'https://github.com/mozilla/addons-server',
        }
        patch = mock.patch(
            'olympia.core.apps.get_version_json',
            return_value=self.default_version_json,
        )
        self.mock_get_version_json = patch.start()
        self.addCleanup(patch.stop)

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

    @mock.patch('olympia.core.apps.connection.cursor')
    def test_db_unavailable_check(self, mock_cursor):
        mock_cursor.side_effect = Exception('Database is unavailable')
        with self.assertRaisesMessage(
            SystemCheckError,
            'Failed to connect to database: Database is unavailable',
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

    def test_missing_version_keys_check(self):
        """
        We expect all required version keys to be set during the docker build.
        """
        for broken_key in REQUIRED_VERSION_KEYS:
            with self.subTest(broken_key=broken_key):
                del self.mock_get_version_json.return_value[broken_key]
                with self.assertRaisesMessage(
                    SystemCheckError,
                    f'{broken_key} is missing from version.json',
                ):
                    call_command('check')
