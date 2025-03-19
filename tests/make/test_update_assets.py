import tempfile
from pathlib import Path
from unittest import TestCase, mock

from scripts.update_assets import clean_static_dirs, update_assets
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
            mock.call(
                ['python3', 'manage.py', 'compress_assets'], check=True, env=mock.ANY
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
                ['python3', 'manage.py', 'collectstatic', '--noinput'],
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
