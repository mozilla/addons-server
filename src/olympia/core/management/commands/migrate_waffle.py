from enum import Enum

from django.core.management.base import CommandError

import olympia.core.logger
from olympia.core.db.migrations import (
    CreateWaffleSwitch,
    DeleteWaffleSwitch,
    RenameWaffleSwitch,
)
from olympia.core.management.commands import BaseMigrationCommand


class Action(Enum):
    ADD = 'add'
    DELETE = 'delete'
    RENAME = 'rename'


class Command(BaseMigrationCommand):
    help = 'Migrate waffle switches (add, delete, rename)'
    log = olympia.core.logger.getLogger('z.core')

    def extend_arguments(self, parser):
        parser.add_argument('name', type=str, help='Name of the waffle switch')
        parser.add_argument(
            '--action',
            type=Action,
            help='Action to perform (add/delete/rename)',
            default=Action.ADD,
        )
        parser.add_argument(
            '--new-name',
            type=str,
            help='New name of the waffle switch',
        )

    def get_operation(self, *args, **options):
        action = Action(options['action'])
        name = options['name']
        new_name = options['new_name']

        if action == Action.RENAME and not new_name:
            raise CommandError('New name is required for rename action')

        if action == Action.ADD:
            return CreateWaffleSwitch(name)
        elif action == Action.DELETE:
            return DeleteWaffleSwitch(name)
        elif action == Action.RENAME:
            return RenameWaffleSwitch(name, new_name)

    def get_name(self, *args, **options):
        return f'waffle_{options["name"]}_{options["action"].value}'
