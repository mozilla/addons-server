import json
from pathlib import Path
from unittest import TestCase

from scripts.health_check_blocks import create_blocks


class TestHealthCheckBlocks(TestCase):
    def setUp(self):
        self.base_data = {
            'version': {
                'data': {'version': '1.0.0'},
                'url': 'http://nginx/__version__',
            },
            'monitors': {
                'data': {'memcache': {'state': True, 'status': ''}},
                'url': 'http://nginx/services/monitor.json',
            },
        }

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

    def _monitor(self, name: str, state: bool, status: str):
        return {name: {'state': state, 'status': status}}

    def test_no_failing_monitors(self):
        self.assertMatchesJsonSnapshot(
            create_blocks(self.base_data),
        )

    def test_one_failing_monitor(self):
        data = dict(self.base_data)
        data.update(
            {
                'monitors': {
                    'data': self._monitor('memcache', False, 'Service is down'),
                    'url': 'http://nginx/services/monitor.json',
                },
            }
        )
        self.assertMatchesJsonSnapshot(
            create_blocks(data),
        )

    def test_multiple_failing_monitors(self):
        data = dict(self.base_data)
        data.update(
            {
                'monitors': {
                    'data': {
                        **self._monitor('cinder', False, 'cinder is down'),
                        **self._monitor('memcache', False, 'Service is down'),
                    },
                    'url': 'http://nginx/services/monitor.json',
                },
            }
        )
        self.assertMatchesJsonSnapshot(create_blocks(data))

    def test_version_with_empty_values(self):
        data = dict(self.base_data)
        data['version'] = {
            'data': {'version': '1.0.0', 'build': '', 'commit': None},
            'url': 'http://nginx/__version__',
        }
        data['monitors'] = {
            'data': self._monitor('memcache', False, 'Service is down'),
            'url': 'http://nginx/services/monitor.json',
        }
        self.assertMatchesJsonSnapshot(create_blocks(data))

    def test_no_version_data(self):
        data = dict(self.base_data)
        data['version'] = {}
        self.assertMatchesJsonSnapshot(create_blocks(data))
