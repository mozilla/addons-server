from django.core.management.base import BaseCommand

from addons.models import (CompatOverrideRange, IncompatibleVersions,
                           update_incompatible_versions)


class Command(BaseCommand):
    """
    Rebuild the incompatible_versions table based on what's in the
    CompatOverrideRange table.
    """
    help = "Clears and rebuilds the incompatible_versions table."

    def handle(self, *args, **options):
        # Clear incompatible_versions table.
        IncompatibleVersions.objects.all().delete()
        # Rebuild it.
        ranges = CompatOverrideRange.objects.all()
        for range in ranges:
            update_incompatible_versions('Mgmt Command', range)
