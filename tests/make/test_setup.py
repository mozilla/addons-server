import os
import unittest
from unittest import mock

from scripts.setup import get_docker_image_meta, main
from tests import override_env


class BaseTestClass(unittest.TestCase):
    def assert_set_env_file_called_with(self, **kwargs):
        result = self.mock_set_env_file.call_args_list[0][0][0]
        for key, value in kwargs.items():
            assert result[key] == value

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
        meta = get_docker_image_meta()
        self.assertEqual(meta['DOCKER_TAG'], 'mozilla/addons-server:local')
        self.assertEqual(meta['DOCKER_TARGET'], 'development')
        self.assertEqual(meta['DOCKER_VERSION'], 'local')
        assert 'DOCKER_DIGEST' not in meta

        with override_env(DOCKER_TARGET='production'):
            meta = get_docker_image_meta()
            self.assertEqual(meta['DOCKER_TARGET'], 'production')

    @override_env(DOCKER_VERSION='test')
    def test_version_overrides_default(self):
        meta = get_docker_image_meta()
        self.assertEqual(meta['DOCKER_TAG'], 'mozilla/addons-server:test')
        self.assertEqual(meta['DOCKER_TARGET'], 'production')
        self.assertEqual(meta['DOCKER_VERSION'], 'test')
        assert 'DOCKER_DIGEST' not in meta

    @override_env(DOCKER_DIGEST='sha256:123')
    def test_digest_overrides_version_and_default(self):
        meta = get_docker_image_meta()
        self.assertEqual(meta['DOCKER_TAG'], 'mozilla/addons-server@sha256:123')
        self.assertEqual(meta['DOCKER_TARGET'], 'production')
        assert 'DOCKER_VERSION' not in meta
        self.assertEqual(meta['DOCKER_DIGEST'], 'sha256:123')

        with override_env(
            DOCKER_VERSION='test',
            DOCKER_DIGEST='sha256:123',
        ):
            meta = get_docker_image_meta()
            self.assertEqual(meta['DOCKER_TAG'], 'mozilla/addons-server@sha256:123')
            self.assertEqual(meta['DOCKER_TARGET'], 'production')
            assert 'DOCKER_VERSION' not in meta
            self.assertEqual(meta['DOCKER_DIGEST'], 'sha256:123')

    @override_env(DOCKER_TAG='image:latest')
    def test_tag_overrides_default_version(self):
        meta = get_docker_image_meta()
        self.assertEqual(meta['DOCKER_TAG'], 'image:latest')
        self.assertEqual(meta['DOCKER_TARGET'], 'production')
        self.assertEqual(meta['DOCKER_VERSION'], 'latest')
        assert 'DOCKER_DIGEST' not in meta

        with override_env(
            DOCKER_TAG='image:latest',
            DOCKER_VERSION='test',
        ):
            meta = get_docker_image_meta()
            self.assertEqual(meta['DOCKER_TAG'], 'image:test')
            self.assertEqual(meta['DOCKER_TARGET'], 'production')
            self.assertEqual(meta['DOCKER_VERSION'], 'test')
            assert 'DOCKER_DIGEST' not in meta

    @override_env(DOCKER_TAG='image@sha256:123')
    def test_tag_overrides_default_digest(self):
        meta = get_docker_image_meta()
        self.assertEqual(meta['DOCKER_TAG'], 'image@sha256:123')
        self.assertEqual(meta['DOCKER_TARGET'], 'production')
        assert 'DOCKER_VERSION' not in meta
        self.assertEqual(meta['DOCKER_DIGEST'], 'sha256:123')

        with mock.patch.dict(os.environ, {'DOCKER_DIGEST': 'test'}):
            meta = get_docker_image_meta()
            self.assertEqual(meta['DOCKER_TAG'], 'image@test')
            self.assertEqual(meta['DOCKER_TARGET'], 'production')
            assert 'DOCKER_VERSION' not in meta
            self.assertEqual(meta['DOCKER_DIGEST'], 'test')

    @override_env(DOCKER_TAG='image:latest')
    def test_version_from_env_file(self):
        self.mock_get_env_file.return_value = {'DOCKER_TAG': 'image:latest'}
        meta = get_docker_image_meta()
        self.assertEqual(meta['DOCKER_TAG'], 'image:latest')
        self.assertEqual(meta['DOCKER_TARGET'], 'production')
        self.assertEqual(meta['DOCKER_VERSION'], 'latest')
        assert 'DOCKER_DIGEST' not in meta

    def test_digest_from_env_file(self):
        self.mock_get_env_file.return_value = {'DOCKER_TAG': 'image@sha256:123'}
        meta = get_docker_image_meta()
        self.assertEqual(meta['DOCKER_TAG'], 'image@sha256:123')
        self.assertEqual(meta['DOCKER_TARGET'], 'production')
        assert 'DOCKER_VERSION' not in meta
        self.assertEqual(meta['DOCKER_DIGEST'], 'sha256:123')

    @override_env(DOCKER_VERSION='')
    def test_default_when_version_is_empty(self):
        meta = get_docker_image_meta()
        self.assertEqual(meta['DOCKER_TAG'], 'mozilla/addons-server:local')
        self.assertEqual(meta['DOCKER_TARGET'], 'development')
        self.assertEqual(meta['DOCKER_VERSION'], 'local')
        assert 'DOCKER_DIGEST' not in meta

        with override_env(DOCKER_VERSION='', DOCKER_TARGET='production'):
            meta = get_docker_image_meta()
            self.assertEqual(meta['DOCKER_TARGET'], 'production')

    @override_env(
        DOCKER_DIGEST='',
        DOCKER_TAG='image@sha256:123',
    )
    def test_default_when_digest_is_empty(self):
        self.mock_get_env_file.return_value = {'DOCKER_TAG': 'image@sha256:123'}
        meta = get_docker_image_meta()
        self.assertEqual(meta['DOCKER_TAG'], 'image@sha256:123')
        self.assertEqual(meta['DOCKER_TARGET'], 'production')
        assert 'DOCKER_VERSION' not in meta
        self.assertEqual(meta['DOCKER_DIGEST'], 'sha256:123')

    def test_version_on_env_file_ignored(self):
        self.mock_get_env_file.return_value = {'DOCKER_VERSION': 'latest'}
        meta = get_docker_image_meta()
        self.assertEqual(meta['DOCKER_VERSION'], 'local')

    def test_commit_on_env_file_ignored(self):
        self.mock_get_env_file.return_value = {'DOCKER_COMMIT': 'commit'}
        meta = get_docker_image_meta()
        assert 'DOCKER_COMMIT' not in meta

    def test_build_on_env_file_ignored(self):
        self.mock_get_env_file.return_value = {'DOCKER_BUILD': 'build'}
        meta = get_docker_image_meta()
        assert 'DOCKER_BUILD' not in meta


@override_env()
class TestDockerTarget(BaseTestClass):
    def test_default_development_target(self):
        main()
        self.assert_set_env_file_called_with(DOCKER_TARGET='development')

    @override_env(DOCKER_VERSION='test')
    def test_default_production_target(self):
        main()
        self.assert_set_env_file_called_with(DOCKER_TARGET='production')

    @override_env()
    def test_default_env_file(self):
        self.mock_get_env_file.return_value = {
            'DOCKER_TAG': 'mozilla/addons-server:test'
        }
        main()
        self.assert_set_env_file_called_with(DOCKER_TARGET='production')

    @override_env(DOCKER_VERSION='latest', DOCKER_COMMIT='abc', DOCKER_BUILD='build')
    def test_env_file_is_ignored_when_building_remote_image(self):
        self.mock_get_env_file.return_value = {
            'DOCKER_TARGET': 'development',
        }
        main(build=True)
        self.assert_set_env_file_called_with(DOCKER_TARGET='production')

    @override_env(DOCKER_VERSION='latest', DOCKER_TARGET='development')
    def test_invalid_remote_development_image(self):
        with self.assertRaises(ValueError):
            main()

    @override_env(DOCKER_TARGET='development')
    def test_invalid_building_development_image(self):
        for version in ['local', 'latest']:
            with self.subTest(version=version):
                with override_env(DOCKER_VERSION=version):
                    with self.assertRaises(ValueError):
                        main(build=True)


@override_env()
class DockerCommitAndBuildMixin:
    @override_env(
        DOCKER_TARGET='production',
        DOCKER_VERSION='local',
    )
    def test_env_file_is_ignored(self):
        """
        The previous commit on a .env file is ignored and so will never be used
        in subsequent runs of make setup.
        """
        self.mock_get_env_file.return_value = {self.key: 'c'}
        main()
        self.assert_set_env_file_called_with(
            DOCKER_TARGET='production',
            DOCKER_VERSION='local',
        )

    def test_forbidden_when_running_remote_image(self):
        with (
            override_env(
                DOCKER_TARGET='production',
                DOCKER_VERSION='latest',
                **{self.key: 'c'},
            ),
            self.assertRaises(ValueError),
        ):
            main()

    def test_required_when_building_remote_image(self):
        for target in ['production', 'development']:
            with self.subTest(target=target):
                with (
                    override_env(
                        DOCKER_TARGET=target,
                        DOCKER_VERSION='latest',
                        **{self.key: ''},
                    ),
                    self.assertRaises(ValueError),
                ):
                    main(build=True)

    def test_irrelevant_when_local_image(self):
        for target in ['production', 'development']:
            for build in [True, False]:
                with self.subTest(target=target, build=build):
                    with (
                        override_env(
                            DOCKER_TARGET=target,
                            DOCKER_VERSION='local',
                            **{self.key: ''},
                        ),
                    ):
                        # We cannot build a development image
                        # so this will fail for a different reason
                        if build and target == 'development':
                            continue
                        else:
                            main(build=build)


class TestDockerCommit(BaseTestClass, DockerCommitAndBuildMixin):
    key = 'DOCKER_COMMIT'


class TestDockerBuild(BaseTestClass, DockerCommitAndBuildMixin):
    key = 'DOCKER_BUILD'


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
class TestMakeDirs(BaseTestClass):
    @mock.patch('scripts.setup.os.makedirs')
    def test_make_dirs(self, mock_makedirs):
        from scripts.setup import root

        main()
        assert mock_makedirs.call_args_list == [
            mock.call(os.path.join(root, dir), exist_ok=True)
            for dir in ['deps', 'site-static', 'static-build', 'storage']
        ]

class TestSiteUrl(BaseTestClass):
    def test_default_site_url(self):
        main()
        self.assert_set_env_file_called_with(SITE_URL='http://olympia.test')

    @override_env(CODESPACE_NAME='test')
    def test_codespace_site_url(self):
        main()
        self.assert_set_env_file_called_with(
            SITE_URL='https://test-80.githubpreview.dev'
        )
