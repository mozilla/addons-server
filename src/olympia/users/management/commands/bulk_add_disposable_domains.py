import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from olympia.core import logger
from olympia.users.tasks import bulk_add_disposable_email_domains


logger = logger.getLogger('z.users')


class Command(BaseCommand):
    help = 'Bulk add disposable email domains (no-op)'

    def add_arguments(self, parser):
        parser.add_argument('file', type=str)

    def handle(self, *args, **options):
        file_path = Path(options['file'])
        if not file_path.exists():
            raise CommandError(f'File {file_path} does not exist')

        records = []
        with file_path.open(newline='') as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header row
            for row in reader:
                if len(row) >= 2:
                    domain, provider = row[0], row[1]
                    records.append((domain, provider))

        result = bulk_add_disposable_email_domains.apply(args=[records])
        logger.info(result)
