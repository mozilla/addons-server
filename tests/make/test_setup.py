import os
import unittest
from unittest import mock

from scripts.setup import get_docker_tag, get_env_file, get_value, main


def override_env(**kwargs):
    return mock.patch.dict(os.environ, kwargs, clear=True)


keys = [
    'COMPOSE_FILE',
    'DOCKER_TAG',
    'DOCKER_TARGET',
    'HOST_UID',
    'DEBUG',
    'DATA_OLYMPIA_MOUNT',
]


class BaseTestClass(unittest.TestCase):
    def assert_set_env_file_called_with(self, **kwargs):
        expected = {key: kwargs.get(key, mock.ANY) for key in keys}
        assert mock.call(expected) in self.mock_set_env_file.call_args_list

    def setUp(self):
        patch = mock.patch('scripts.setup.set_env_file')
        self.addCleanup(patch.stop)
        self.mock_set_env_file = patch.start()

        patch_two = mock.patch('scripts.setup.get_env_file', return_value={})
        self.addCleanup(patch_two.stop)
        self.mock_get_env_file = patch_two.start()


@override_env()
class TestGetEnvFile(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp_dir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp_dir, 'test_env')

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_dir)

    def _write_and_assert(self, value, expected, write_value=True):
        if write_value:
            with open(self.path, 'w') as f:
                f.write(f'key="{value}"')
        expected_value = {'key': expected} if type(expected) is str else expected
        self.assertEqual(get_env_file(self.path), expected_value)

    def test_get_env_file_missing(self):
        self._write_and_assert('value', {}, write_value=False)

    def test_get_value_default(self):
        self._write_and_assert('value', 'value')

    def test_get_empty_value(self):
        self._write_and_assert('', '')

    def test_get_quoted_value(self):
        self._write_and_assert('"quoted_value"', '"quoted_value"')

    def test_get_single_quoted_value(self):
        self._write_and_assert("'quoted_value'", "'quoted_value'")

    def test_get_unmatched_quotes(self):
        self._write_and_assert('"unmatched_quote', '"unmatched_quote')

    def test_get_nested_quotes(self):
        self._write_and_assert(
            'value with "nested" quotes', 'value with "nested" quotes'
        )


@override_env()
class TestGetValue(BaseTestClass):
    @override_env(TEST_KEY='env_value')
    def test_get_value_from_environment(self):
        """Test that get_value returns value from environment
        when key exists and is not empty
        """
        value = get_value('TEST_KEY', 'default')
        self.assertEqual(value, 'env_value')

    @override_env(TEST_KEY='')
    def test_get_value_empty_environment(self):
        """Test that get_value falls back to env file
        when environment value is empty string
        """
        self.mock_get_env_file.return_value = {'TEST_KEY': 'file_value'}
        value = get_value('TEST_KEY', 'default')
        self.assertEqual(value, 'file_value')

    def test_get_value_missing_environment(self):
        """Test that get_value falls back to env file
        when key doesn't exist in environment
        """
        self.mock_get_env_file.return_value = {'TEST_KEY': 'file_value'}
        value = get_value('TEST_KEY', 'default')
        self.assertEqual(value, 'file_value')

    def test_get_value_from_env_file(self):
        """Test that get_value returns value from env file
        when present and environment fallback enabled
        """
        self.mock_get_env_file.return_value = {'TEST_KEY': 'file_value'}
        value = get_value('TEST_KEY', 'default')
        self.assertEqual(value, 'file_value')

    def test_get_value_env_file_disabled(self):
        """Test that get_value skips env file check when from_file=False"""
        self.mock_get_env_file.return_value = {'TEST_KEY': 'file_value'}
        value = get_value('TEST_KEY', 'default', from_file=False)
        self.assertEqual(value, 'default')

    def test_get_value_default(self):
        """Test that get_value returns default value
        when not in environment or env file
        """
        self.mock_get_env_file.return_value = {}
        value = get_value('TEST_KEY', 'default')
        self.assertEqual(value, 'default')

    def test_get_value_default_with_env_file_disabled(self):
        """Test that get_value returns default when not in environment
        and env file check disabled
        """
        self.mock_get_env_file.return_value = {'TEST_KEY': 'file_value'}
        value = get_value('TEST_KEY', 'default', from_file=False)
        self.assertEqual(value, 'default')

    @override_env(TEST_KEY='env_value')
    def test_get_value_precedence(self):
        """Test that environment value takes precedence
        over env file value
        """
        self.mock_get_env_file.return_value = {'TEST_KEY': 'file_value'}
        value = get_value('TEST_KEY', 'default')
        self.assertEqual(value, 'env_value')

    def test_get_value_empty_env_file(self):
        """Test behavior when env file exists but value is empty/None"""
        self.mock_get_env_file.return_value = {'TEST_KEY': None}
        value = get_value('TEST_KEY', 'default')
        self.assertEqual(value, 'default')

    def test_get_value_missing_env_file(self):
        """Test behavior when env file is missing or can't be read"""
        self.mock_get_env_file.return_value = {}
        value = get_value('TEST_KEY', 'default')
        self.assertEqual(value, 'default')


@override_env()
class TestGetDockerTag(BaseTestClass):
    def test_default_value_is_local(self):
        tag, version, digest = get_docker_tag()
        self.assertEqual(tag, 'mozilla/addons-server:local')
        self.assertEqual(version, 'local')
        self.assertEqual(digest, None)

    @override_env(DOCKER_VERSION='test')
    def test_version_overrides_default(self):
        tag, version, digest = get_docker_tag()
        self.assertEqual(tag, 'mozilla/addons-server:test')
        self.assertEqual(version, 'test')
        self.assertEqual(digest, None)

    @override_env(DOCKER_DIGEST='sha256:123')
    def test_digest_overrides_version_and_default(self):
        tag, version, digest = get_docker_tag()
        self.assertEqual(tag, 'mozilla/addons-server@sha256:123')
        self.assertEqual(version, None)
        self.assertEqual(digest, 'sha256:123')

        with override_env(DOCKER_VERSION='test', DOCKER_DIGEST='sha256:123'):
            tag, version, digest = get_docker_tag()
            self.assertEqual(tag, 'mozilla/addons-server@sha256:123')
            self.assertEqual(version, None)
            self.assertEqual(digest, 'sha256:123')

    @override_env(DOCKER_TAG='image:latest')
    def test_tag_overrides_default_version(self):
        tag, version, digest = get_docker_tag()
        self.assertEqual(tag, 'image:latest')
        self.assertEqual(version, 'latest')
        self.assertEqual(digest, None)

        with override_env(DOCKER_TAG='image:latest', DOCKER_VERSION='test'):
            tag, version, digest = get_docker_tag()
            self.assertEqual(tag, 'image:test')
            self.assertEqual(version, 'test')
            self.assertEqual(digest, None)

    @override_env(DOCKER_TAG='image@sha256:123')
    def test_tag_overrides_default_digest(self):
        tag, version, digest = get_docker_tag()
        self.assertEqual(tag, 'image@sha256:123')
        self.assertEqual(version, None)
        self.assertEqual(digest, 'sha256:123')

        with mock.patch.dict(os.environ, {'DOCKER_DIGEST': 'test'}):
            tag, version, digest = get_docker_tag()
            self.assertEqual(tag, 'image@test')
            self.assertEqual(version, None)
            self.assertEqual(digest, 'test')

    def test_version_from_env_file(self):
        self.mock_get_env_file.return_value = {'DOCKER_TAG': 'image:latest'}
        tag, version, digest = get_docker_tag()
        self.assertEqual(tag, 'image:latest')
        self.assertEqual(version, 'latest')
        self.assertEqual(digest, None)

    def test_digest_from_env_file(self):
        self.mock_get_env_file.return_value = {'DOCKER_TAG': 'image@sha256:123'}
        tag, version, digest = get_docker_tag()
        self.assertEqual(tag, 'image@sha256:123')
        self.assertEqual(version, None)
        self.assertEqual(digest, 'sha256:123')

    @override_env(DOCKER_VERSION='')
    def test_default_when_version_is_empty(self):
        tag, version, digest = get_docker_tag()
        self.assertEqual(tag, 'mozilla/addons-server:local')
        self.assertEqual(version, 'local')
        self.assertEqual(digest, None)

    @override_env(DOCKER_DIGEST='')
    def test_default_when_digest_is_empty(self):
        self.mock_get_env_file.return_value = {'DOCKER_TAG': 'image@sha256:123'}
        tag, version, digest = get_docker_tag()
        self.assertEqual(tag, 'image@sha256:123')
        self.assertEqual(version, None)
        self.assertEqual(digest, 'sha256:123')


@override_env()
class TestDockerTarget(BaseTestClass):
    def test_default_development_target(self):
        main()
        self.assert_set_env_file_called_with(DOCKER_TARGET='development')

    @override_env(DOCKER_VERSION='test')
    def test_default_production_target(self):
        main()
        self.assert_set_env_file_called_with(DOCKER_TARGET='production')

    def test_default_env_file(self):
        self.mock_get_env_file.return_value = {
            'DOCKER_TAG': 'mozilla/addons-server:test'
        }
        main()
        self.assert_set_env_file_called_with(DOCKER_TARGET='production')


@override_env()
class TestComposeFile(BaseTestClass):
    def test_default_compose_file(self):
        main()
        self.assert_set_env_file_called_with(COMPOSE_FILE='docker-compose.yml')

    @override_env(COMPOSE_FILE='test')
    def test_compose_file_override(self):
        main()
        self.assert_set_env_file_called_with(COMPOSE_FILE='test')


@override_env()
class TestDebug(BaseTestClass):
    def test_default_debug(self):
        main()
        self.assert_set_env_file_called_with(DEBUG='True')

    @override_env(DOCKER_TARGET='production')
    def test_production_debug(self):
        main()
        self.assert_set_env_file_called_with(DEBUG='False')

    @override_env(DOCKER_TARGET='production')
    def test_override_env_debug_false_on_target_production(self):
        self.mock_get_env_file.return_value = {'DEBUG': 'True'}
        main()
        self.assert_set_env_file_called_with(DEBUG='False')

    @override_env(DOCKER_TARGET='development')
    def test_override_env_debug_true_on_target_development(self):
        self.mock_get_env_file.return_value = {'DEBUG': 'False'}
        main()
        self.assert_set_env_file_called_with(DEBUG='True')

    @override_env(DEBUG='test')
    def test_debug_override(self):
        main()
        self.assert_set_env_file_called_with(DEBUG='test')


@override_env()
class TestMountOlympia(BaseTestClass):
    def test_default_mount_olympia_on_default_target(self):
        main()
        self.assert_set_env_file_called_with(DATA_OLYMPIA_MOUNT='development')

    @override_env(MOUNT_OLYMPIA='test')
    def test_cannot_override_mount_olympia_on_default_target(self):
        main()
        self.assert_set_env_file_called_with(DATA_OLYMPIA_MOUNT='development')

    @override_env(DOCKER_TARGET='development', MOUNT_OLYMPIA='test')
    def test_cannot_override_mount_olympia_on_development(self):
        main()
        self.assert_set_env_file_called_with(DATA_OLYMPIA_MOUNT='development')

    @override_env(DOCKER_TARGET='production')
    def test_default_mount_olympia_on_production_target(self):
        main()
        self.assert_set_env_file_called_with(DATA_OLYMPIA_MOUNT='production')

    @override_env(DOCKER_TARGET='production', MOUNT_OLYMPIA='development')
    def test_override_mount_olympia_on_production_target(self):
        main()
        self.assert_set_env_file_called_with(DATA_OLYMPIA_MOUNT='development')
