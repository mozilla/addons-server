import os
import unittest
from unittest import mock

from scripts.setup import get_docker_image_meta, main
from tests import override_env


keys = [
    'DOCKER_TAG',
    'DOCKER_TARGET',
    'HOST_UID',
    'OLYMPIA_DEPS',
    'DEBUG',
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
class TestGetDockerTag(BaseTestClass):
    def test_default_value_is_local(self):
        tag, target, version, digest = get_docker_image_meta()
        self.assertEqual(tag, 'mozilla/addons-server:local')
        self.assertEqual(target, 'development')
        self.assertEqual(version, 'local')
        self.assertEqual(digest, None)

        with override_env(DOCKER_TARGET='production'):
            _, target, _, _ = get_docker_image_meta()
            self.assertEqual(target, 'production')

    @override_env(DOCKER_VERSION='test')
    def test_version_overrides_default(self):
        tag, target, version, digest = get_docker_image_meta()
        self.assertEqual(tag, 'mozilla/addons-server:test')
        self.assertEqual(target, 'production')
        self.assertEqual(version, 'test')
        self.assertEqual(digest, None)

    @override_env(DOCKER_DIGEST='sha256:123')
    def test_digest_overrides_version_and_default(self):
        tag, target, version, digest = get_docker_image_meta()
        self.assertEqual(tag, 'mozilla/addons-server@sha256:123')
        self.assertEqual(target, 'production')
        self.assertEqual(version, None)
        self.assertEqual(digest, 'sha256:123')

        with override_env(DOCKER_VERSION='test', DOCKER_DIGEST='sha256:123'):
            tag, target, version, digest = get_docker_image_meta()
            self.assertEqual(tag, 'mozilla/addons-server@sha256:123')
            self.assertEqual(target, 'production')
            self.assertEqual(version, None)
            self.assertEqual(digest, 'sha256:123')

    @override_env(DOCKER_TAG='image:latest')
    def test_tag_overrides_default_version(self):
        tag, target, version, digest = get_docker_image_meta()
        self.assertEqual(tag, 'image:latest')
        self.assertEqual(target, 'production')
        self.assertEqual(version, 'latest')
        self.assertEqual(digest, None)

        with override_env(DOCKER_TAG='image:latest', DOCKER_VERSION='test'):
            tag, target, version, digest = get_docker_image_meta()
            self.assertEqual(tag, 'image:test')
            self.assertEqual(target, 'production')
            self.assertEqual(version, 'test')
            self.assertEqual(digest, None)

    @override_env(DOCKER_TAG='image@sha256:123')
    def test_tag_overrides_default_digest(self):
        tag, target, version, digest = get_docker_image_meta()
        self.assertEqual(tag, 'image@sha256:123')
        self.assertEqual(target, 'production')
        self.assertEqual(version, None)
        self.assertEqual(digest, 'sha256:123')

        with mock.patch.dict(os.environ, {'DOCKER_DIGEST': 'test'}):
            tag, target, version, digest = get_docker_image_meta()
            self.assertEqual(tag, 'image@test')
            self.assertEqual(target, 'production')
            self.assertEqual(version, None)
            self.assertEqual(digest, 'test')

    def test_version_from_env_file(self):
        self.mock_get_env_file.return_value = {'DOCKER_TAG': 'image:latest'}
        tag, target, version, digest = get_docker_image_meta()
        self.assertEqual(tag, 'image:latest')
        self.assertEqual(target, 'production')
        self.assertEqual(version, 'latest')
        self.assertEqual(digest, None)

    def test_digest_from_env_file(self):
        self.mock_get_env_file.return_value = {'DOCKER_TAG': 'image@sha256:123'}
        tag, target, version, digest = get_docker_image_meta()
        self.assertEqual(tag, 'image@sha256:123')
        self.assertEqual(target, 'production')
        self.assertEqual(version, None)
        self.assertEqual(digest, 'sha256:123')

    @override_env(DOCKER_VERSION='')
    def test_default_when_version_is_empty(self):
        tag, target, version, digest = get_docker_image_meta()
        self.assertEqual(tag, 'mozilla/addons-server:local')
        self.assertEqual(target, 'development')
        self.assertEqual(version, 'local')
        self.assertEqual(digest, None)

        with override_env(DOCKER_VERSION='', DOCKER_TARGET='production'):
            _, target, _, _ = get_docker_image_meta()
            self.assertEqual(target, 'production')

    @override_env(DOCKER_DIGEST='', DOCKER_TAG='image@sha256:123')
    def test_default_when_digest_is_empty(self):
        self.mock_get_env_file.return_value = {'DOCKER_TAG': 'image@sha256:123'}
        tag, target, version, digest = get_docker_image_meta()
        self.assertEqual(tag, 'image@sha256:123')
        self.assertEqual(target, 'production')
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
class TestOlympiaDeps(BaseTestClass):
    def test_default_olympia_deps(self):
        main()
        self.assert_set_env_file_called_with(OLYMPIA_DEPS='development')

    @override_env(DOCKER_TARGET='production')
    def test_production_olympia_deps(self):
        main()
        self.assert_set_env_file_called_with(OLYMPIA_DEPS='production')

    @override_env(DOCKER_TARGET='production')
    def test_override_env_olympia_deps_development_on_target_production(self):
        self.mock_get_env_file.return_value = {'OLYMPIA_DEPS': 'development'}
        main()
        self.assert_set_env_file_called_with(OLYMPIA_DEPS='production')

    @override_env(DOCKER_TARGET='development')
    def test_override_env_olympia_deps_development_on_target_development(self):
        self.mock_get_env_file.return_value = {'OLYMPIA_DEPS': 'production'}
        main()
        self.assert_set_env_file_called_with(OLYMPIA_DEPS='development')

    @override_env(OLYMPIA_DEPS='test')
    def test_olympia_deps_override(self):
        main()
        self.assert_set_env_file_called_with(OLYMPIA_DEPS='test')


@override_env()
@mock.patch('scripts.setup.os.makedirs')
def test_make_dirs(mock_makedirs):
    from scripts.setup import root

    main()
    assert mock_makedirs.call_args_list == [
        mock.call(os.path.join(root, dir), exist_ok=True)
        for dir in ['deps', 'site-static', 'static-build', 'storage']
    ]
