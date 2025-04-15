import tempfile
from pathlib import Path
from unittest import mock

from scripts.setup import CREATE_PATHS, REMOVE_PATHS, get_docker_image_meta, main
from tests import override_env
from tests.make import BaseTestClass


@override_env()
class TestDockerImageMeta(BaseTestClass):
    def test_default_values(self):
        result = get_docker_image_meta(self.env)
        self.assertEqual(result['DOCKER_TAG'], 'mozilla/addons-server:local')
        self.assertEqual(result['DOCKER_VERSION'], 'local')
        assert 'DOCKER_DIGEST' not in result
        self.assertEqual(result['DOCKER_TARGET'], 'development')
        assert 'DOCKER_COMMIT' not in result
        assert 'DOCKER_BUILD' not in result

    def test_missing_docker_tag_should_raise(self):
        with self.assertRaises(ValueError):
            self.env.write_env_file({'DOCKER_TAG': ''})
            get_docker_image_meta(self.env)

    @mock.patch('scripts.setup.parse_docker_tag', return_value=('image', None, None))
    def test_missing_docker_version_should_raise(self, mock_parse_docker_tag):
        with self.assertRaises(ValueError):
            get_docker_image_meta(self.env)

    @mock.patch(
        'scripts.setup.parse_docker_tag', return_value=('image', 'remote', None)
    )
    def test_missing_docker_digest_on_remote_image_should_raise(
        self, mock_parse_docker_tag
    ):
        with self.assertRaises(ValueError):
            get_docker_image_meta(self.env)

    def test_missing_docker_digest_on_local_latest_image_should_not_raise(self):
        for version in ['local', 'latest']:
            with mock.patch(
                'scripts.setup.parse_docker_tag',
                return_value=('tag', 'image', version, None),
            ):
                get_docker_image_meta(self.env)

    @mock.patch(
        'scripts.setup.parse_docker_tag', return_value=('image', 'latest', 'digest')
    )
    def test_defined_docker_digest_on_build_should_raise(self, mock_parse_docker_tag):
        with self.assertRaises(ValueError):
            get_docker_image_meta(self.env, is_build=True)

    def test_docker_target_override_from_file_ignored(self):
        self.env.write_env_file({'DOCKER_TARGET': 'production'})
        result = get_docker_image_meta(self.env)
        self.assertEqual(result['DOCKER_TARGET'], 'development')

    @override_env(
        DOCKER_COMMIT='commit', DOCKER_BUILD='build', DOCKER_TARGET='production'
    )
    def test_docker_target_production(self):
        self.env.write_env_file({'DOCKER_TAG': 'latest'})
        get_docker_image_meta(self.env, is_build=True)

    @override_env(
        DOCKER_COMMIT='commit',
        DOCKER_BUILD='build',
        DOCKER_TARGET='development',
    )
    def test_docker_target_development_on_build_should_raise(self):
        with self.assertRaises(ValueError):
            self.env.write_env_file({'DOCKER_TAG': 'image:latest'})
            self.assertEqual(self.env.get('DOCKER_TARGET'), 'development')
            get_docker_image_meta(self.env, is_build=True)

    @override_env(DOCKER_TARGET='development')
    def test_docker_target_development_on_non_local_image_raises(self):
        with self.assertRaises(ValueError):
            self.env.write_env_file({'DOCKER_TAG': 'image:latest'})
            get_docker_image_meta(self.env)

    @override_env()
    def test_docker_commit_and_build_required_on_build(self):
        with self.assertRaises(ValueError):
            self.env.write_env_file({'DOCKER_TAG': 'image:latest'})
            get_docker_image_meta(self.env, is_build=True)

    @override_env(DOCKER_COMMIT='commit', DOCKER_BUILD='build')
    def test_docker_commit_and_build_on_non_build_should_raise(self):
        with self.assertRaises(ValueError):
            self.env.write_env_file({'DOCKER_TAG': 'image:latest'})
            get_docker_image_meta(self.env)

    @override_env(DOCKER_VERSION='version')
    def test_docker_version_on_env_should_raise(self):
        with self.assertRaises(ValueError):
            get_docker_image_meta(self.env)

    @override_env(DOCKER_DIGEST='digest')
    def test_docker_digest_on_env_should_raise(self):
        with self.assertRaises(ValueError):
            get_docker_image_meta(self.env)


@override_env()
class TestMain(BaseTestClass):
    def run_setup(self, is_build=False):
        """
        Run the setup script with the given arguments, always dry-running.
        """
        return main(self.root, '.env', is_build, dry_run=True)

    def test_main(self):
        self.env.write_env_file({'DOCKER_TAG': 'latest'})
        result = self.run_setup()
        assert isinstance(result, dict)
        self.assertEqual(result['DOCKER_VERSION'], 'latest')

    def test_main_with_build(self):
        # Set an invalid build argument. we cannot build a development image.
        # This confirms that the build argument is passed to the metadata function.
        self.env.write_env_file({'DOCKER_TAG': 'development'})
        with self.assertRaises(ValueError):
            self.run_setup(is_build=True)

    def test_main_with_dry_run_does_not_write_files(self):
        for dir in REMOVE_PATHS:
            remove_path = self.root / dir
            if not remove_path.exists():
                if remove_path.is_dir():
                    remove_path.mkdir(parents=True, exist_ok=True)
                else:
                    remove_path.mkdir(parents=True, exist_ok=True)
                    remove_path.touch()

        result = self.run_setup()
        assert isinstance(result, dict)

        self.assertFalse((self.root / '.env').exists())

        for dir in CREATE_PATHS:
            self.assertFalse((self.root / dir).exists())

        for dir in REMOVE_PATHS:
            remove_path = self.root / dir
            self.assertTrue(remove_path.exists())

    def test_debug_default_to_opposite_of_docker_target(self):
        for docker_target, expected_debug in [
            ('development', True),
            ('production', False),
        ]:
            with (
                self.subTest(docker_target=docker_target),
                override_env(DOCKER_TARGET=docker_target),
            ):
                result = self.run_setup()
                self.assertEqual(result['DEBUG'], expected_debug)

    @override_env(DOCKER_TARGET='production')
    def test_debug_from_file_ignored(self):
        self.env.write_env_file({'DEBUG': 'true'})
        result = self.run_setup()
        self.assertEqual(result['DEBUG'], False)

    @override_env(DEBUG=True, DOCKER_TARGET='production')
    def test_debug_from_env_overrides(self):
        result = self.run_setup()
        self.assertEqual(result['DEBUG'], True)

    @override_env(DOCKER_TARGET='production')
    def test_olympia_deps_defaults_to_docker_target(self):
        result = self.run_setup()
        self.assertEqual(result['OLYMPIA_DEPS'], 'production')

    @override_env(DOCKER_TARGET='production')
    def test_olympia_deps_override_from_file_ignored(self):
        self.env.write_env_file({'OLYMPIA_DEPS': 'development'})
        result = self.run_setup()
        self.assertEqual(result['OLYMPIA_DEPS'], 'production')

    @override_env(OLYMPIA_DEPS='development', DOCKER_TARGET='production')
    def test_olympia_deps_from_env_overrides_docker_target(self):
        result = self.run_setup()
        self.assertEqual(result['OLYMPIA_DEPS'], 'development')

    @mock.patch('os.getuid', return_value=123)
    def test_olympia_id_always_from_os(self, mock_getuid):
        result = self.run_setup()
        self.assertEqual(result['HOST_UID'], 123)

    def test_none_values_not_in_result(self):
        result = self.run_setup()
        assert 'DOCKER_COMMIT' not in result
        assert 'DOCKER_BUILD' not in result


@override_env()
class TestMakeDirs(BaseTestClass):
    def test_make_dirs(self):
        tmpdir = tempfile.mkdtemp()
        root = Path(tmpdir)

        main(root, '.env', False, False)

        for dir in ['deps', 'site-static', 'static-build', 'storage']:
            self.assertTrue((root / dir).exists())
