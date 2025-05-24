import os
import json
import unittest
from pathlib import Path


def override_env(**kwargs):
    return unittest.mock.patch.dict(os.environ, kwargs, clear=True)

class TestCase(unittest.TestCase):
    def assertEqualDicts(self, result: dict, expected: dict):
        import json

        left = json.dumps(result, indent=2, sort_keys=True)
        right = json.dumps(expected, indent=2, sort_keys=True)

        if left != right:
            import difflib

            diff = difflib.unified_diff(
                left.splitlines(True),
                right.splitlines(True),
                fromfile='actual',
                tofile='expected',
            )
            self.fail('\n' + ''.join(diff))

    def assertMatchesJsonSnapshot(self, result):
        snapshot_dir = Path(__file__).parent / 'snapshots' / self.__class__.__name__
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        name = self._testMethodName

        snapshot_path = snapshot_dir / f'{name}.json'

        if not snapshot_path.exists():
            snapshot_path.write_text(json.dumps(result, indent=2, sort_keys=True))

        with snapshot_path.open('r') as f:
            snapshot = json.load(f)

        self.assertEqualDicts(result, snapshot)

