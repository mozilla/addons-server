import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, mock
from unittest.mock import Mock, patch

import pytest

from scripts.compile_locales import compile_locales, process_po_file
from tests import override_env


@pytest.mark.needs_locales_compilation
class TestCompileLocales(TestCase):
    def setUp(self):
        self.home_dir = Path(tempfile.mkdtemp())
        self.locale_dir = (self.home_dir / 'locale').mkdir()

    @patch.dict(sys.modules, {'dennis': None})
    def test_dennis_not_installed(self):
        """Test that the script raises when dennis is not installed"""
        self.assertRaises(ImportError, compile_locales)

    @patch.dict(sys.modules, {'dennis': Mock()})
    @patch('scripts.compile_locales.ThreadPoolExecutor')
    def test_process_po_file(self, mock_executor):
        """Test that the script processes po files"""
        # Create po files
        django_po = self.home_dir / 'locale' / 'django.po'
        django_po.touch()
        djangojs_po = self.home_dir / 'locale' / 'djangojs.po'
        djangojs_po.touch()

        # Setup ThreadPoolExecutor mock
        mock_executor_instance = Mock()
        mock_executor.return_value.__enter__.return_value = mock_executor_instance

        with override_env(HOME=self.home_dir.as_posix()):
            compile_locales()

        # Get the actual arguments passed to map
        actual_args = mock_executor_instance.map.call_args[0]
        self.assertEqual(actual_args[0], process_po_file)
        self.assertEqual(list(actual_args[1]), [django_po, djangojs_po])


class TestProcessPoFile(TestCase):
    def setUp(self):
        self.pofile = Path(tempfile.mkdtemp()) / 'django.po'

        mock_subprocess = patch('scripts.compile_locales.subprocess.run')
        self.mock_subprocess = mock_subprocess.start()
        self.addCleanup(mock_subprocess.stop)

    def test_process_po_file(self):
        process_po_file(self.pofile.as_posix())
        self.assertTrue(self.pofile.with_suffix('.mo').exists())

        assert self.mock_subprocess.call_args_list == [
            mock.call(
                ['dennis-cmd', 'lint', '--errorsonly', self.pofile.as_posix()],
                capture_output=True,
                check=False,
            ),
            mock.call(
                [
                    'msgfmt',
                    '-o',
                    self.pofile.with_suffix('.mo'),
                    self.pofile.as_posix(),
                ],
                check=True,
            ),
        ]

    def test_process_po_file_retries(self):
        self.mock_subprocess.side_effect = subprocess.CalledProcessError(
            returncode=1,
            cmd=['dennis-cmd', 'lint', '--errorsonly', self.pofile.as_posix()],
        )

        with self.assertRaises(subprocess.CalledProcessError):
            process_po_file(self.pofile.as_posix())

        self.assertTrue(self.pofile.with_suffix('.mo').exists())

        # We expect 3 attempts to process the file
        self.assertEqual(self.mock_subprocess.call_count, 3)
