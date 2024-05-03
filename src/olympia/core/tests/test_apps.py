from unittest import mock

from django.core.management import call_command
from django.core.management.base import SystemCheckError
from django.test import SimpleTestCase


class SystemCheckIntegrationTest(SimpleTestCase):
    def test_uwsgi_check(self):
        call_command('check')

        with mock.patch('olympia.core.apps.subprocess') as subprocess:
            subprocess.run.return_value.returncode = 127
            with self.assertRaisesMessage(
                SystemCheckError, 'uwsgi --version returned a non-zero value'
            ):
                call_command('check')

    def test_version_check_missing_file(self):
        call_command('check')

        with mock.patch('olympia.core.apps.get_version_json') as get_version_json:
            get_version_json.return_value = None
            with self.assertRaisesMessage(SystemCheckError, 'version.json is missing'):
                call_command('check')

    def test_version_missing_key(self):
        call_command('check')

        with mock.patch('olympia.core.apps.get_version_json') as get_version_json:
            keys = ['version', 'build', 'commit', 'source']
            version_mock = {key: 'test' for key in keys}

            for key in keys:
                version = version_mock.copy()
                version.pop(key)
                get_version_json.return_value = version

                with self.assertRaisesMessage(
                    SystemCheckError, f'{key} is missing from version.json'
                ):
                    call_command('check')

    def test_version_missing_multiple_keys(self):
        call_command('check')

        with mock.patch('olympia.core.apps.get_version_json') as get_version_json:
            get_version_json.return_value = {'version': 'test', 'build': 'test'}
            with self.assertRaisesMessage(
                SystemCheckError, 'commit, source is missing from version.json'
            ):
                call_command('check')
