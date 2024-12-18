import unittest
from unittest import mock

from scripts.install_deps import copy_package_json, main
from tests import override_env


@mock.patch('scripts.install_deps.shutil.copy')
class TestCopyPackageJson(unittest.TestCase):
    def test_copy_package_json(self, mock_shutil):
        copy_package_json()
        assert mock_shutil.call_args_list == [
            mock.call('/data/olympia/package.json', '/deps'),
            mock.call('/data/olympia/package-lock.json', '/deps'),
        ]

    def test_copy_package_json_no_files(self, mock_shutil):
        mock_shutil.side_effect = IOError
        copy_package_json()
        assert mock_shutil.call_args_list == [
            mock.call('/data/olympia/package.json', '/deps'),
        ]


class TestInstallDeps(unittest.TestCase):
    def setUp(self):
        mocks = ['shutil.rmtree', 'os.listdir', 'subprocess.run', 'copy_package_json']
        self.mocks = {}
        for mock_name in mocks:
            patch = mock.patch(
                f'scripts.install_deps.{mock_name}',
            )
            self.mocks[mock_name] = patch.start()
            self.addCleanup(patch.stop)

    def test_raises_no_targets(self):
        """
        Test that the function raises a ValueError if
        no or invalid targets are specified
        """
        for argument in [None, '', []]:
            with self.assertRaises(ValueError):
                main(argument)

    def _test_remove_existing_deps(self, args, expect_remove=False):
        self.mocks['os.listdir'].return_value = [
            'cache',
            'lib',
            'node_modules',
            'package.json',
            'package-lock.json',
        ]
        with override_env(
            **{
                'PIP_COMMAND': 'pip-test',
                'NPM_ARGS': 'npm-test',
                **args,
            }
        ):
            main(['prod'])

        if expect_remove:
            assert self.mocks['os.listdir'].called
            assert self.mocks['shutil.rmtree'].call_args_list == [
                mock.call('/deps/lib'),
                mock.call('/deps/node_modules'),
            ]
        else:
            assert not self.mocks['os.listdir'].called
            assert not self.mocks['shutil.rmtree'].called

    def test_keep_deps_for_local_mixed_env(self):
        """Test that dependencies are kept when running
        locally with development deps in production"""
        args = {
            'DOCKER_TAG': 'local',
            'OLYMPIA_DEPS': 'development',
            'DOCKER_TARGET': 'production',
        }
        self._test_remove_existing_deps(args, expect_remove=False)

    def test_keep_deps_for_local_default(self):
        """Test that dependencies are kept when running locally with default settings"""
        args = {'DOCKER_TAG': 'local', 'OLYMPIA_DEPS': 'development'}
        self._test_remove_existing_deps(args, expect_remove=False)

    def test_remove_deps_for_non_local(self):
        """Test that dependencies are removed when running in production environment"""
        args = {'DOCKER_TAG': 'prod'}
        self._test_remove_existing_deps(args, expect_remove=True)

    def test_remove_deps_for_prod_deps_in_dev(self):
        """Test that dependencies are removed when
        installing production deps in development"""
        args = {
            'DOCKER_TAG': 'local',
            'OLYMPIA_DEPS': 'production',
            'DOCKER_TARGET': 'development',
        }
        self._test_remove_existing_deps(args, expect_remove=True)

    def test_remove_deps_for_prod_deps_in_prod(self):
        """Test that dependencies are removed when
        installing production deps in production"""
        args = {
            'DOCKER_TAG': 'local',
            'OLYMPIA_DEPS': 'production',
            'DOCKER_TARGET': 'production',
        }
        self._test_remove_existing_deps(args, expect_remove=True)

    def test_copy_package_json_called(self):
        """Test that copy_package_json is called"""
        main(['prod'])
        assert self.mocks['copy_package_json'].called

    @override_env(PIP_COMMAND='pip-test', NPM_ARGS='npm-test')
    def test_pip_command_set_on_environment(self):
        main(['prod'])
        assert self.mocks['subprocess.run'].call_args_list[0][0][0][0] == 'pip-test'

    @override_env()
    def test_pip_command_not_set_on_environment(self):
        self.assertRaises(KeyError, main, ['prod'])

    @override_env(NPM_ARGS='npm-test', PIP_COMMAND='pip-test')
    def test_npm_command_set_on_environment(self):
        main(['prod'])
        assert 'npm-test' in self.mocks['subprocess.run'].call_args_list[1][0][0]

    @override_env()
    def test_npm_command_not_set_on_environment(self):
        self.assertRaises(KeyError, main, ['prod'])

    def test_correct_args_passed_to_subprocesses(self):
        """
        Test that the correct arguments are passed to the subprocesses
        """
        main(['pip', 'prod', 'dev'])

        assert self.mocks['subprocess.run'].call_args_list == [
            mock.call(
                [
                    'python3',
                    '-m',
                    'pip',
                    'install',
                    '--progress-bar=off',
                    '--no-deps',
                    '--exists-action=w',
                    '-r',
                    'requirements/pip.txt',
                    '-r',
                    'requirements/prod.txt',
                    '-r',
                    'requirements/dev.txt',
                ],
                check=True,
            ),
            # NPM excludes the pip target
            mock.call(
                [
                    'npm',
                    'install',
                    '--no-save',
                    '--no-audit',
                    '--no-fund',
                    '--prefix',
                    '/deps/',
                    '--cache',
                    '/deps/cache/npm',
                    '--loglevel',
                    'verbose',
                    '--include',
                    'prod',
                    '--include',
                    'dev',
                ],
                check=True,
            ),
        ]
