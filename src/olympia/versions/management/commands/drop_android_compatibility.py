import csv

from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia import amo
from olympia.addons.tasks import index_addons
from olympia.versions.models import ApplicationsVersions


log = olympia.core.logger.getLogger('z.versions.drop_android_compatibility')


class Command(BaseCommand):
    """
    Drop Firefox for Android compatibility on *all* versions of the add-ons in
    the provided csv.

    The caller should make sure the csv contains all the add-ons we want to
    drop compatibility for.
    """

    help = 'Drop compatibility with Firefox for Android on specified add-ons'

    def add_arguments(self, parser):
        parser.add_argument(
            'CSVFILE',
            help='Path to CSV file containing add-on ids.',
        )

    def read_csv(self, path):
        with open(path) as file_:
            csv_reader = csv.reader(file_)
            # Format should be a single column with the add-on id.
            # Ignore non-decimal to avoid the column header.
            return [
                int(row[0])
                for row in csv_reader
                if row[0] and row[0].strip().isdecimal()
            ]

    def handle(self, *args, **kwargs):
        addon_ids = self.read_csv(kwargs['CSVFILE'])
        ApplicationsVersions.objects.filter(
            version__addon__id__in=addon_ids, application=amo.ANDROID.id
        ).delete()
        index_addons.delay(addon_ids)
