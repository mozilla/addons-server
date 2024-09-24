from datetime import datetime

from ..base import BaseDataCommand


class Command(BaseDataCommand):
    help = 'Dump data with a specified name'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            type=str,
            default=datetime.now().strftime('%Y%m%d%H%M%S'),
            help='Name of the data dump',
        )
        parser.add_argument(
            '--force', action='store_true', help='Force overwrite of existing dump'
        )

    def handle(self, *args, **options):
        name = options.get('name')
        force = options.get('force')

        dump_path = self.backup_dir_path(name)
        db_path = self.backup_db_path(name)
        storage_path = self.backup_storage_path(name)

        self.make_dir(dump_path, force=force)

        self.call_command(
            'dbbackup',
            output_path=db_path,
            interactive=False,
            compress=True,
        )

        self.call_command(
            'mediabackup',
            output_path=storage_path,
            interactive=False,
            compress=True,
        )
