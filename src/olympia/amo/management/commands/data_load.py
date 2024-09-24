from ..base import BaseDataCommand


class Command(BaseDataCommand):
    help = 'Load data from a specified name'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            type=str,
            required=True,
            help='Name of the data dump',
        )

    def handle(self, *args, **options):
        name = options.get('name')
        db_path = self.backup_db_path(name)
        storage_path = self.backup_storage_path(name)

        self.call_command(
            'dbrestore',
            input_path=db_path,
            interactive=False,
            uncompress=True,
        )

        self.call_command(
            'mediarestore',
            input_path=storage_path,
            interactive=False,
            uncompress=True,
            replace=True,
        )

        # reindex --wipe will force the ES mapping to be re-installed.
        # After loading data from a backup, we should always reindex
        # to make sure the mapping is correct.
        self.call_command('reindex', '--wipe', '--force', '--noinput')
