import tempfile
from pathlib import Path
from unittest import TestCase, mock

from scripts.update_assets import build_pinguino, clean_static_dirs, update_assets
from tests import override_env


class TestUpdateAssets(TestCase):
    def setUp(self):
        self.mocks = {}
        for name in ['clean_static_dirs', 'subprocess.run']:
            patch = mock.patch(f'scripts.update_assets.{name}')
            self.mocks[name] = patch.start()
            self.addCleanup(patch.stop)

    def test_update_assets(self):
        update_assets()

        assert self.mocks['clean_static_dirs'].call_count == 1

        assert self.mocks['subprocess.run'].call_args_list == [
            mock.call(['npm', 'run', 'build'], check=True, env=mock.ANY),
            # The Pinguino SPA is installed and built (into static/) before
            # collectstatic runs below.
            mock.call(
                ['npm', 'ci', '--no-audit', '--no-fund'],
                check=True,
                cwd=mock.ANY,
                env=mock.ANY,
            ),
            mock.call(
                ['npm', 'run', 'build'],
                check=True,
                cwd=mock.ANY,
                env=mock.ANY,
            ),
            mock.call(
                ['python3', 'manage.py', 'generate_jsi18n_files'],
                check=True,
                env=mock.ANY,
            ),
            mock.call(
                ['python3', 'manage.py', 'generate_js_swagger_files'],
                check=True,
                env=mock.ANY,
            ),
            mock.call(
                ['python3', 'manage.py', 'collectstatic', '--noinput', '--clear'],
                check=True,
                env=mock.ANY,
            ),
        ]

        for call in self.mocks['subprocess.run'].call_args_list:
            assert (
                call.kwargs['env']['DJANGO_SETTINGS_MODULE']
                == 'olympia.lib.settings_base'
            )

    def test_update_assets_with_verbose(self):
        update_assets(verbose=True)

        assert self.mocks['clean_static_dirs'].call_args_list == [
            mock.call(True),
        ]

    def test_build_pinguino(self):
        home = Path(tempfile.mkdtemp())
        with override_env(HOME=home.as_posix()):
            build_pinguino({'DJANGO_SETTINGS_MODULE': 'olympia.lib.settings_base'})

        pinguino_dir = home / 'src' / 'pinguino' / 'devhub'
        # Both commands run from the SPA project directory.
        assert self.mocks['subprocess.run'].call_args_list == [
            mock.call(
                ['npm', 'ci', '--no-audit', '--no-fund'],
                check=True,
                cwd=pinguino_dir,
                env=mock.ANY,
            ),
            mock.call(
                ['npm', 'run', 'build'],
                check=True,
                cwd=pinguino_dir,
                env=mock.ANY,
            ),
        ]

        expected_cache = str(home / 'deps' / 'cache' / 'npm')
        for call in self.mocks['subprocess.run'].call_args_list:
            # npm is pointed at the shared cache via an absolute path so it does
            # not scatter one inside the SPA project.
            assert call.kwargs['env']['npm_config_cache'] == expected_cache
            # The passed-in environment is preserved.
            assert (
                call.kwargs['env']['DJANGO_SETTINGS_MODULE']
                == 'olympia.lib.settings_base'
            )


class TestCleanStaticDirs(TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())

    def _run_clean_static_dirs(self, verbose=False):
        with override_env(HOME=self.home.as_posix()):
            clean_static_dirs(verbose=verbose)

    def test_creates_dirs(self):
        self._run_clean_static_dirs()

        assert self.home.joinpath('static-build').exists()
        assert self.home.joinpath('site-static').exists()

    def test_empties_dirs(self):
        self.home.joinpath('static-build').mkdir()
        (self.home / 'static-build' / 'test.txt').touch()

        self.home.joinpath('site-static').mkdir()
        (self.home / 'site-static' / 'test.txt').touch()

        self._run_clean_static_dirs()

        assert not (self.home / 'static-build' / 'test.txt').exists()
        assert not (self.home / 'site-static' / 'test.txt').exists()
