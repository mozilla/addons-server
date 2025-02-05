from django.core.management.base import BaseCommand, CommandError

from olympia.core.utils import get_version_json


class BaseLandfillCommand(BaseCommand):
    def assert_local_dev_mode(self):
        if get_version_json().get('version') != 'local':
            raise CommandError(
                'This command is only available in local development mode.'
            )
