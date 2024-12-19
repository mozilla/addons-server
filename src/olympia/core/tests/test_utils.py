import json
import os
import shutil
import sys
import tempfile
from unittest import TestCase, mock

from olympia.core.utils import get_version_json


default_version = {
    'commit': '',
    'version': 'local',
    'build': '',
    'target': 'development',
    'source': 'https://github.com/mozilla/addons-server',
}


class TestGetVersionJson(TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.build_info_path = os.path.join(self.tmp_dir, 'build-info')
        self.pkg_json_path = os.path.join(self.tmp_dir, 'package.json')

        self.with_build_info()
        self.with_pkg_json({})

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def with_build_info(self, **kwargs):
        data = json.dumps({**default_version, **kwargs})
        with open(self.build_info_path, 'w') as f:
            f.write(data)

    def with_pkg_json(self, data):
        with open(self.pkg_json_path, 'w') as f:
            f.write(json.dumps(data))

    def test_get_version_json_defaults(self):
        result = get_version_json(build_info_path=self.build_info_path)

        assert result['commit'] == default_version['commit']
        assert result['version'] == default_version['version']
        assert result['build'] == default_version['build']
        assert result['source'] == default_version['source']

    def test_get_version_json_commit(self):
        self.with_build_info(commit='new_commit')
        result = get_version_json(build_info_path=self.build_info_path)

        assert result['commit'] == 'new_commit'

    def test_get_version_json_version(self):
        self.with_build_info(version='new_version')
        result = get_version_json(build_info_path=self.build_info_path)

        assert result['version'] == 'new_version'

    def test_get_version_json_build(self):
        self.with_build_info(build='new_build')
        result = get_version_json(build_info_path=self.build_info_path)

        assert result['build'] == 'new_build'

    def test_get_version_json_python(self):
        with mock.patch.object(sys, 'version_info') as v_info:
            v_info.major = 3
            v_info.minor = 9
            result = get_version_json(build_info_path=self.build_info_path)

        assert result['python'] == '3.9'

    def test_get_version_json_django(self):
        with mock.patch('django.VERSION', (3, 2)):
            result = get_version_json(build_info_path=self.build_info_path)

        assert result['django'] == '3.2'

    def test_get_version_json_addons_linter(self):
        self.with_pkg_json({'dependencies': {'addons-linter': '1.2.3'}})
        result = get_version_json(
            build_info_path=self.build_info_path,
            pkg_json_path=self.pkg_json_path,
        )

        assert result['addons-linter'] == '1.2.3'

    def test_get_version_json_addons_linter_missing_package(self):
        self.with_pkg_json({'dependencies': {}})
        result = get_version_json(
            build_info_path=self.build_info_path,
            pkg_json_path=self.pkg_json_path,
        )

        assert result['addons-linter'] == ''

    def test_get_version_json_addons_linter_missing_file(self):
        result = get_version_json(
            build_info_path=self.build_info_path,
            pkg_json_path=self.pkg_json_path,
        )

        assert result['addons-linter'] == ''
