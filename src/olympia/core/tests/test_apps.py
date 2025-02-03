import json
import os
import tempfile
from unittest import mock

from django.core.management import CommandError, call_command
from django.core.management.base import SystemCheckError
from django.test import TestCase, override_settings

import responses

from olympia.core.utils import REQUIRED_VERSION_KEYS


class BaseCheckTestCase(TestCase):
    """Base class for all system check tests with common setup and utilities."""

    def setUp(self):
        super().setUp()
        # Create temporary directories
        self.temp_dirs = {
            'media_root': tempfile.mkdtemp(prefix='media-root-'),
            'static_root': tempfile.mkdtemp(prefix='static-root-'),
            'static_build': tempfile.mkdtemp(prefix='static-build-'),
        }

        # Setup default version.json data
        self.default_version_json = {
            'tag': 'mozilla/addons-server:1.0',
            'target': 'development',
            'commit': 'abc',
            'version': '1.0',
            'build': 'http://example.com/build',
            'source': 'https://github.com/mozilla/addons-server',
        }

        # Setup mocks
        self._setup_mocks()

        # Create some default files
        self.create_test_files()

        # Setup responses for nginx checks
        self._setup_nginx_responses()

    def _setup_mocks(self):
        """Setup all required mocks."""
        # Version.json mock
        patcher = mock.patch('olympia.core.apps.get_version_json')
        self.mock_version = patcher.start()
        self.mock_version.return_value = self.default_version_json
        self.addCleanup(patcher.stop)

        # Database cursor mock
        patcher = mock.patch('olympia.core.apps.connection.cursor')
        self.mock_db = patcher.start()
        self.mock_db.return_value.__enter__.return_value.fetchone.return_value = (
            'character_set_database',
            'utf8mb4',
        )
        self.addCleanup(patcher.stop)

        # uWSGI mock
        patcher = mock.patch('olympia.core.apps.subprocess')
        self.mock_uwsgi = patcher.start()
        self.mock_uwsgi.run.return_value.returncode = 0
        self.addCleanup(patcher.stop)

        # User ID mock
        patcher = mock.patch('olympia.core.apps.getpwnam')
        self.mock_uid = patcher.start()
        self.mock_uid.return_value.pw_uid = 9500
        self.addCleanup(patcher.stop)

        # Compress assets mock
        patcher = mock.patch('olympia.core.apps.call_command')
        self.mock_compress = patcher.start()
        self.mock_compress.return_value = None
        self.addCleanup(patcher.stop)

    def _setup_nginx_responses(self):
        """Setup responses for nginx checks."""
        responses.reset()

        # Setup successful responses for all nginx endpoints
        test_urls = [
            'http://nginx/user-media/test.txt',
            'http://nginx/static/test.txt',
        ]

        for url in test_urls:
            responses.add(
                responses.GET,
                url,
                status=200,
                body=self.temp_dirs['media_root'],
                headers={'X-Served-By': 'nginx'},
            )

    def create_test_files(self):
        """Create default test files in temporary directories."""
        # Create static build manifest
        self.manifest_path = os.path.join(
            self.temp_dirs['static_build'], 'static-build.json'
        )
        with open(self.manifest_path, 'w') as f:
            json.dump({'app.js': {'file': 'app.123.js'}}, f)

        # Create compressed CSS file
        self.css_file = os.path.join(self.temp_dirs['static_root'], 'foo.css')
        with open(self.css_file, 'w') as f:
            f.write('body { background: red; }')

        # Create the app.js file referenced in manifest
        self.js_file = os.path.join(self.temp_dirs['static_root'], 'app.123.js')
        with open(self.js_file, 'w') as f:
            f.write('console.log("test");')

        self.mock_compress.side_effect = lambda command, dry_run, stdout: stdout.write(
            f'{self.css_file}\n{self.js_file}'
        )

    def assertSystemCheckRaises(self, message):
        """Assert that the system check raises an exception with the given message."""
        with self.assertRaisesMessage(SystemCheckError, message):
            call_command('check')

    def tearDown(self):
        """Clean up temporary directories."""
        responses.reset()
        for temp_dir in self.temp_dirs.values():
            try:
                for root, dirs, files in os.walk(temp_dir, topdown=False):
                    for name in files:
                        os.remove(os.path.join(root, name))
                    for name in dirs:
                        os.rmdir(os.path.join(root, name))
                os.rmdir(temp_dir)
            except (OSError, IOError):
                pass
        super().tearDown()


class FileSystemCheckTests(BaseCheckTestCase):
    """Tests focusing on file system states affecting checks."""

    @responses.activate
    def test_all_files_present_development(self):
        """Test when all required files exist in development mode."""
        with override_settings(
            TARGET='production',
            MEDIA_ROOT=self.temp_dirs['media_root'],
            STATIC_ROOT=self.temp_dirs['static_root'],
            STATIC_BUILD_MANIFEST_PATH=self.manifest_path,
            HOST_UID='9500',
        ):
            # If the compress_assets command returns the correct files -> None
            call_command('check')
            # If the compress_assets comamand raises -> SystemCheckError
            self.mock_compress.side_effect = CommandError('Unexpected error')
            self.assertSystemCheckRaises(
                'Error running compress_assets command: Unexpected error'
            )
            # If compress_assets command returns no files -> SystemCheckError
            self.mock_compress.side_effect = lambda command, dry_run, stdout: None
            self.assertSystemCheckRaises('No compressed asset files were found.')

    def test_missing_static_build_manifest(self):
        """Test behavior when static build manifest is missing."""
        os.remove(self.manifest_path)
        with override_settings(
            MEDIA_ROOT=self.temp_dirs['media_root'],
            STATIC_ROOT=self.temp_dirs['static_root'],
            STATIC_BUILD_MANIFEST_PATH=self.manifest_path,
            TARGET='production',
            HOST_UID='9500',
        ):
            self.assertSystemCheckRaises('Static build manifest file does not exist')

    def test_missing_media_root(self):
        """Test behavior when media root directory is missing."""
        with override_settings(
            TARGET='development',
            ENV='local',
            MEDIA_ROOT='/fake/not/real/directory',
            STATIC_ROOT=self.temp_dirs['static_root'],
            STATIC_BUILD_MANIFEST_PATH=self.manifest_path,
            HOST_UID='9500',
        ):
            self.assertSystemCheckRaises('/fake/not/real/directory does not exist')

    def test_invalid_manifest_content(self):
        """Test behavior with invalid manifest content."""
        with open(self.manifest_path, 'w') as f:
            json.dump({'app.js': {'file': 'missing.js'}}, f)

        with override_settings(
            MEDIA_ROOT=self.temp_dirs['media_root'],
            STATIC_ROOT=self.temp_dirs['static_root'],
            STATIC_BUILD_MANIFEST_PATH=self.manifest_path,
            TARGET='production',
            HOST_UID='9500',
        ):
            self.assertSystemCheckRaises(
                'Static asset app.js does not exist at ' 'expected path: '
            )


class ServiceStateTests(BaseCheckTestCase):
    """Tests focusing on service availability and responses."""

    def test_database_unavailable(self):
        """Test behavior when database is unavailable."""
        self.mock_db.side_effect = Exception('Database is unavailable')
        with override_settings(HOST_UID='9500'):
            self.assertSystemCheckRaises(
                'Failed to connect to database: Database is unavailable'
            )

    def test_invalid_database_charset(self):
        """Test behavior with wrong database charset."""
        self.mock_db.return_value.__enter__.return_value.fetchone.return_value = (
            'character_set_database',
            'utf8mb3',
        )
        with override_settings(HOST_UID='9500'):
            self.assertSystemCheckRaises('Database charset invalid')

    def test_uwsgi_unavailable(self):
        """Test behavior when uWSGI is not available."""
        self.mock_uwsgi.run.return_value.returncode = 1
        with override_settings(HOST_UID='9500'):
            self.assertSystemCheckRaises('uwsgi --version returned a non-zero value')

    @responses.activate
    def test_nginx_responses(self):
        """Test various nginx response scenarios."""
        self.default_version_json['target'] = 'development'

        # Test various response scenarios
        test_cases = [
            (404, 'content', 'nginx'),
            (200, 'wrong', 'nginx'),
            (200, 'content', 'apache'),
        ]

        for status, content, server in test_cases:
            responses.reset()
            responses.add(
                responses.GET,
                'http://nginx/user-media/test.txt',
                status=status,
                body=content,
                headers={'X-Served-By': server},
            )
            responses.add(
                responses.GET,
                'http://nginx/static/test.txt',
                status=status,
                body=content,
                headers={'X-Served-By': server},
            )

            with override_settings(
                TARGET='development',
                ENV='local',
                MEDIA_ROOT=self.temp_dirs['media_root'],
                STATIC_ROOT=self.temp_dirs['static_root'],
                STATIC_BUILD_MANIFEST_PATH=self.manifest_path,
                HOST_UID='9500',
            ):
                self.assertSystemCheckRaises('Failed to access')


class ConfigurationTests(BaseCheckTestCase):
    """Tests focusing on different configuration combinations."""

    def test_host_uid_configurations(self):
        """Test various HOST_UID configurations."""
        test_cases = [
            (None, 9500, None),  # Default production
            (None, 1000, 'Expected user uid to be 9500'),  # Wrong UID in prod
            ('1000', 1000, None),  # Correct custom UID
            ('1000', 2000, 'Expected user uid to be 1000'),  # Wrong custom UID
        ]

        for host_uid, actual_uid, expected_error in test_cases:
            self.mock_uid.return_value.pw_uid = actual_uid
            with override_settings(
                TARGET='production',
                HOST_UID=host_uid,
                MEDIA_ROOT=self.temp_dirs['media_root'],
                STATIC_ROOT=self.temp_dirs['static_root'],
                STATIC_BUILD_MANIFEST_PATH=self.manifest_path,
            ):
                if expected_error:
                    self.assertSystemCheckRaises(expected_error)
                else:
                    call_command('check')

    def test_version_json_requirements(self):
        """Test version.json requirements."""
        # Test missing each required key
        for key in REQUIRED_VERSION_KEYS:
            version_data = self.default_version_json.copy()
            del version_data[key]
            self.mock_version.return_value = version_data

            with override_settings(HOST_UID='9500'):
                with self.assertRaisesRegex(
                    Exception, rf'{key} is missing from version.json'
                ):
                    call_command('check')


class CombinedScenariosTests(BaseCheckTestCase):
    """Tests multiple failing checks together."""

    def test_multiple_service_failures(self):
        """Test behavior when multiple services are unavailable."""
        # Make database unavailable
        self.mock_db.side_effect = Exception('Database is unavailable')
        # Make uWSGI unavailable
        self.mock_uwsgi.run.return_value.returncode = 1

        with override_settings(HOST_UID='9500'):
            self.assertSystemCheckRaises(
                'Failed to connect to database: Database is unavailable'
            )

    def test_multiple_file_issues(self):
        """Test behavior with multiple missing files."""

        with override_settings(
            MEDIA_ROOT='/fake/not/real/directory',
            STATIC_ROOT=self.temp_dirs['static_root'],
            STATIC_BUILD_MANIFEST_PATH='/fake/not/real.json',
            TARGET='production',
            HOST_UID='9500',
        ):
            self.assertSystemCheckRaises(
                'Static build manifest file does not exist: ' '/fake/not/real.json'
            )

    def test_configuration_and_service_issues(self):
        """Test combination of configuration and service issues."""
        # Invalid HOST_UID and database charset
        self.mock_uid.return_value.pw_uid = 1000
        self.mock_db.return_value.__enter__.return_value.fetchone.return_value = (
            'character_set_database',
            'utf8mb3',
        )

        with override_settings(HOST_UID=None):
            self.assertSystemCheckRaises('Expected user uid to be 9500')
