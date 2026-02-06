import json
import os
import tempfile
from unittest import mock

from django.conf import settings
from django.core.management import call_command
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

        self.media_root = tempfile.mkdtemp(prefix='media-root')
        self.static_root = tempfile.mkdtemp(prefix='static-root')
        self.manifest_path = os.path.join(
            tempfile.mkdtemp(prefix='manifest-dir'), 'manifest.json'
        )

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

    @override_settings(STATIC_BUILD_MANIFEST_PATH='/nonexistent/path/manifest.json')
    def test_static_check_manifest_does_not_exist(self):
        """Test that an error is raised when the manifest file doesn't exist."""
        with self.assertRaisesMessage(
            SystemCheckError,
            'Static build manifest file does not exist: '
            '/nonexistent/path/manifest.json',
        ):
            call_command('check')

    @override_settings(STATIC_ROOT='/static/root', STATIC_BUILD_MANIFEST_PATH=None)
    def test_static_check_manifest_references_nonexistent_files(self):
        """Test that an error is raised when manifest references non-existent files."""
        # Create a temporary manifest file with references to non-existent files
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            manifest_content = {
                'app.js': {'file': 'app.123abc.js'},
                'styles.css': {'file': 'styles.456def.css'},
            }
            json.dump(manifest_content, f)
            manifest_path = f.name

        with override_settings(STATIC_BUILD_MANIFEST_PATH=manifest_path):
            with self.assertRaisesMessage(
                SystemCheckError,
                'Static asset app.js does not exist at expected path: '
                '/static/root/app.123abc.js',
            ):
                call_command('check')

        os.unlink(manifest_path)

    @override_settings(STATIC_BUILD_MANIFEST_PATH=None)
    def test_static_check_empty_manifest(self):
        """Test that no error is raised with an empty manifest."""
        # Create an empty manifest file
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            json.dump({}, f)
            manifest_path = f.name

        with override_settings(STATIC_BUILD_MANIFEST_PATH=manifest_path):
            # No error should be raised with an empty manifest
            call_command('check')

        os.unlink(manifest_path)

    def test_static_check_valid_manifest(self):
        """Test that no error is raised when manifest references existing files."""
        # Create a temporary static root with actual files
        static_root = tempfile.mkdtemp(prefix='static-root-valid')

        # Create the asset files
        asset1_path = os.path.join(static_root, 'app.123abc.js')
        asset2_path = os.path.join(static_root, 'styles.456def.css')

        with open(asset1_path, 'w') as f:
            f.write('console.log("test");')

        with open(asset2_path, 'w') as f:
            f.write('body { color: blue; }')

        # Create a manifest file that references these files
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            manifest_content = {
                'app.js': {'file': 'app.123abc.js'},
                'styles.css': {'file': 'styles.456def.css'},
            }
            json.dump(manifest_content, f)
            manifest_path = f.name

        with override_settings(
            STATIC_ROOT=static_root, STATIC_BUILD_MANIFEST_PATH=manifest_path
        ):
            # No error should be raised with a valid manifest
            call_command('check')

        # Clean up
        os.unlink(manifest_path)
        os.unlink(asset1_path)
        os.unlink(asset2_path)
        os.rmdir(static_root)

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

    def _test_nginx_response(self, status_code=200, body='', served_by='nginx'):
        self.mock_get_version_json.return_value['target'] = 'development'
        url = f'http://nginx{settings.MEDIA_URL_PREFIX}test.txt'

        responses.add(
            responses.GET,
            url,
            status=status_code,
            body=body,
            headers={'X-Served-By': served_by},
        )

        expected_config = (
            (status_code, 200),
            (body, self.media_root),
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
        self._test_nginx_response(status_code=404)

    def test_nginx_raises_unexpected_content(self):
        """Test that files return the expected content."""
        self._test_nginx_response(body='foo')

    def test_nginx_raises_unexpected_served_by(self):
        """Test that files are served by nginx and not redirected elsewhere."""
        self._test_nginx_response(served_by='wow')
