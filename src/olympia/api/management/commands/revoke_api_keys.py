import csv

from django.core.management.base import BaseCommand
from django.db import transaction

from olympia.api.models import APIKey


class Command(BaseCommand):
    help = 'Revoke the API (secret, key) tuples from specified csv file.'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=unicode)

    def handle(self, *args, **options):
        revoked_count = 0
        with open(options['csv_file'], 'rb') as csvfile:
            for idx, (key, secret) in enumerate(csv.reader(csvfile), start=1):
                try:
                    apikey = APIKey.objects.get(key=key, is_active=True)
                except APIKey.DoesNotExist:
                    self.stdout.write(
                        'Ignoring APIKey {}, it does not exist.\n'.format(key))
                    continue
                if apikey.secret != secret:
                    self.stdout.write(
                        'Ignoring APIKey {}, secret differs.\n'.format(key))
                    continue
                else:
                    with transaction.atomic():
                        apikey.update(is_active=None)
                        APIKey.new_jwt_credentials(user=apikey.user)
                    revoked_count += 1
                    self.stdout.write(
                        'Revoked APIKey {}.\n'.format(key))
            self.stdout.write(
                'Done. Revoked {} keys out of {} entries.'.format(
                    revoked_count, idx))
