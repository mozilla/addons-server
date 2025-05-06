import csv

from django.core.management.base import BaseCommand
from django.db.transaction import atomic

import olympia.core.logger
from olympia import amo
from olympia.addons.models import Addon
from olympia.applications.models import AppVersion
from olympia.versions.models import ApplicationsVersions


log = olympia.core.logger.getLogger('z.versions.force_min_android_compatibility')


class Command(BaseCommand):
    """
    Force current version of add-ons in the specified csv to be compatible with
    Firefox for Android <MIN_VERSION_FENIX_GENERAL_AVAILABILITY> and higher.

    Should not affect compatibility of add-ons recommended/line for Android.
    """

    help = (
        'Force add-ons to be compatible with Firefox for Android '
        f'{amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY} and higher'
    )

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
        min_version_fenix = AppVersion.objects.get(
            application=amo.ANDROID.id,
            version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
        )
        max_version_fenix = AppVersion.objects.get(
            application=amo.ANDROID.id, version=amo.DEFAULT_WEBEXT_MAX_VERSION
        )
        addons = (
            Addon.objects.filter(pk__in=addon_ids)
            .no_transforms()
            .select_related('_current_version', '_current_version__file')
            .prefetch_related('promotedaddon')
        )
        count = 0
        skipped = 0
        for addon in addons:
            if addon.can_be_compatible_with_all_fenix_versions:
                log.info(
                    'Skipping add-on id %d because it can be compatible with Fenix.',
                    addon.pk,
                )
                skipped += 1
                continue
            with atomic():
                ApplicationsVersions.objects.update_or_create(
                    version=addon.current_version,
                    application=amo.ANDROID.id,
                    defaults={
                        'min': min_version_fenix,
                        'max': max_version_fenix,
                        'originated_from': amo.APPVERSIONS_ORIGINATED_FROM_MIGRATION,
                    },
                )
                count += 1
        log.info(
            'Done forcing Android compatibility on %d add-ons (%d skipped)',
            count,
            skipped,
        )
