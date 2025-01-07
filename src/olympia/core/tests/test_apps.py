import os
import tempfile
from unittest import mock

from django.core.management import CommandError, call_command
from django.core.management.base import SystemCheckError
from django.test import TestCase
from django.test.utils import override_settings

import responses

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
        )
        self.mock_get_version_json = patch.start()
        self.mock_get_version_json.return_value = self.default_version_json
        self.addCleanup(patch.stop)

        mock_dir = tempfile.mkdtemp(prefix='static-root')
        self.fake_css_file = os.path.join(mock_dir, 'foo.css')
        with open(self.fake_css_file, 'w') as f:
            f.write('body { background: red; }')

        patch_command = mock.patch('olympia.core.apps.call_command')
        self.mock_call_command = patch_command.start()
        self.mock_call_command.side_effect = (
            lambda command, dry_run, stdout: stdout.write(f'{self.fake_css_file}\n')
        )
        self.addCleanup(patch_command.stop)

        self.media_root = tempfile.mkdtemp(prefix='media-root')

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

    @override_settings(HOST_UID=None)
    @mock.patch('olympia.core.apps.getpwnam')
    def test_illegal_override_uid_check(self, mock_getpwnam):
        """
        In production, or when HOST_UID is not set, we expect to not override
        the default uid of 9500 for the olympia user.
        """
        mock_getpwnam.return_value.pw_uid = 1000
        with self.assertRaisesMessage(
            SystemCheckError,
            'Expected user uid to be 9500',
        ):
            call_command('check')

        with override_settings(HOST_UID=1000):
            call_command('check')

    def test_static_check_no_assets_found(self):
        """
        Test static_check fails if compress_assets reports no files.
        """
        self.mock_get_version_json.return_value['target'] = 'production'
        # Simulate "compress_assets" returning no file paths.
        self.mock_call_command.side_effect = (
            lambda command, dry_run, stdout: stdout.write('')
        )
        with self.assertRaisesMessage(
            SystemCheckError, 'No compressed asset files were found.'
        ):
            call_command('check')

    @mock.patch('os.path.exists')
    def test_static_check_missing_assets(self, mock_exists):
        """
        Test static_check fails if at least one specified compressed
        asset file does not exist.
        """
        self.mock_get_version_json.return_value['target'] = 'production'
        # Simulate "compress_assets" returning a couple of files.
        self.mock_call_command.side_effect = (
            lambda command, dry_run, stdout: stdout.write(
                f'{self.fake_css_file}\nfoo.js\n'
            )
        )
        # Pretend neither file exists on disk.
        mock_exists.return_value = False

        with self.assertRaisesMessage(
            SystemCheckError,
            # Only the first missing file triggers the AssertionError message check
            'Compressed asset file does not exist: foo.js',
        ):
            call_command('check')

    def test_static_check_command_error(self):
        """
        Test static_check fails if there's an error during compress_assets.
        """
        self.mock_get_version_json.return_value['target'] = 'production'
        self.mock_call_command.side_effect = CommandError('Oops')
        with self.assertRaisesMessage(
            SystemCheckError, 'Error running compress_assets command: Oops'
        ):
            call_command('check')

    def test_static_check_command_success(self):
        """
        Test static_check succeeds if compress_assets runs without errors.
        """
        self.mock_get_version_json.return_value['target'] = 'production'
        self.mock_call_command.side_effect = (
            lambda command, dry_run, stdout: stdout.write(f'{self.fake_css_file}\n')
        )
        call_command('check')

    def test_nginx_skips_check_on_production_target(self):
        fake_media_root = '/fake/not/real'
        with override_settings(MEDIA_ROOT=fake_media_root):
            call_command('check')

    def test_nginx_raises_missing_directory(self):
        self.mock_get_version_json.return_value['target'] = 'development'
        fake_media_root = '/fake/not/real'
        with override_settings(MEDIA_ROOT=fake_media_root):
            with self.assertRaisesMessage(
                SystemCheckError,
                f'{fake_media_root} does not exist',
            ):
                call_command('check')

    def _test_nginx_response(
        self, base_url, status_code=200, response_text='', served_by='nginx'
    ):
        self.mock_get_version_json.return_value['target'] = 'development'
        url = f'{base_url}/test.txt'

        responses.add(
            responses.GET,
            url,
            status=status_code,
            body=response_text,
            headers={'X-Served-By': served_by},
        )

        expected_config = (
            (status_code, 200),
            (response_text, self.media_root),
            (served_by, 'nginx'),
        )

        with override_settings(MEDIA_ROOT=self.media_root):
            with self.assertRaisesMessage(
                SystemCheckError,
                f'Failed to access {url}. {expected_config}',
            ):
                call_command('check')

    def test_nginx_raises_non_200_status_code(self):
        """Test that files return a 200 status code."""
        self._test_nginx_response('http://nginx/user-media', status_code=404)

    def test_nginx_raises_unexpected_content(self):
        """Test that files return the expected content."""
        self._test_nginx_response('http://nginx/user-media', response_text='foo')

    def test_nginx_raises_unexpected_served_by(self):
        """Test that files are served by nginx and not redirected elsewhere."""
        self._test_nginx_response('http://nginx/user-media', served_by='wow')
