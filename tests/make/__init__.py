import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.utils import Env
from tests import override_env


@override_env()
class BaseTestClass(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root.as_posix())
        self.env = Env(self.root / '.env')
