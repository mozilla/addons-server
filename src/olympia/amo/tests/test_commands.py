# -*- coding: utf-8 -*-
import os
from importlib import import_module

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test.utils import override_settings

import mock
import pytest


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


@override_settings(
    CRON_JOBS={'sample_cron_job': 'olympia.amo.tests.test_commands'})
def test_cron_command_no_job():
    with pytest.raises(CommandError) as error_info:
        call_command('cron')
    assert 'These jobs are available:' in str(error_info.value)
    assert 'sample_cron_job' in str(error_info.value)


def test_cron_command_invalid_job():
    with pytest.raises(CommandError) as error_info:
        call_command('cron', 'made_up_job')
    assert 'Unrecognized job name: made_up_job' in str(error_info.value)


def test_cron_jobs_setting():
    for name, path in settings.CRON_JOBS.iteritems():
        module = import_module(path)
        getattr(module, name)


@override_settings(
    MINIFY_BUNDLES={'css': {'common_multi': [
        'css/zamboni/admin-django.css',
        'css/zamboni/admin-mozilla.css']}})
@mock.patch('olympia.lib.jingo_minify_helpers.subprocess')
def test_compress_assets_command_without_git(subprocess_mock):
    build_id_file = os.path.realpath(os.path.join(settings.ROOT, 'build.py'))
    assert os.path.exists(build_id_file)

    with open(build_id_file) as f:
        contents_before = f.read()

    # Call command a second time. We should get a different build id, since it
    # depends on a uuid.
    call_command('compress_assets', use_uuid=True)
    with open(build_id_file) as f:
        contents_after = f.read()

    assert contents_before != contents_after
