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
