import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_process_addons_invalid_task():
    with pytest.raises(CommandError):
        call_command('process_addons', task='foo')
