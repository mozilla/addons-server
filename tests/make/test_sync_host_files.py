import json
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from scripts.sync_host_files import sync_host_files
from tests import override_env


@mock.patch('scripts.sync_host_files.subprocess.run')
class TestSyncHostFiles(TestCase):
    def test_sync_host_files(self, mock_subprocess):
        sync_host_files()

        mock_subprocess.assert_has_calls(
            [
                mock.call(['make', 'update_deps'], check=True),
                # mock.call(['make', 'compile_locales'], check=True),
                # mock.call(['make', 'update_assets'], check=True),
            ]
        )

    def test_sync_host_files_production(self, mock_subprocess):
        mock_build = Path(tempfile.mktemp())
        mock_build.write_text(json.dumps({'target': 'production'}))

        with override_env(BUILD_INFO=mock_build.as_posix()):
            sync_host_files()

        mock_subprocess.assert_has_calls(
            [
                mock.call(['make', 'update_deps'], check=True),
                mock.call(['make', 'compile_locales'], check=True),
                mock.call(['make', 'update_assets'], check=True),
            ]
        )
