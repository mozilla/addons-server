# -*- coding: utf-8 -*-
import mock
from importlib import import_module

from django.conf import settings
from django.core.management import call_command
from django.test.utils import override_settings


def sample_cron_job(*args):
    pass


@override_settings(
    CRON_JOBS={'sample_cron_job': 'olympia.amo.tests.test_commands'})
@mock.patch('olympia.amo.tests.test_commands.sample_cron_job')
def test_cron_command(_mock):
    assert _mock.call_count == 0
    call_command('cron', 'sample_cron_job', 'arg1', 'arg2')
    assert _mock.call_count == 1
    _mock.assert_called_with('arg1', 'arg2')


def test_cron_jobs_setting():
    for name, path in settings.CRON_JOBS.iteritems():
        module = import_module(path)
        getattr(module, name)
