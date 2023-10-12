from django.conf import settings
from django.core.management.base import BaseCommand

import olympia.core.logger
from olympia import amo
from olympia.applications.models import AppVersion
from olympia.versions.compare import version_int
from olympia.versions.models import ApplicationsVersions


log = olympia.core.logger.getLogger('z.versions.bump_min_android_compatibility')


class Command(BaseCommand):
    """
    Bump minimum Firefox for Android compatibility to
    <MIN_VERSION_FENIX_GENERAL_AVAILABILITY>.

    This command should be reused everytime we change the value of
    MIN_VERSION_FENIX_GENERAL_AVAILABILITY (in either direction, as long as
    it's higher than 119.0a1).
    """

    def handle(self, **kwargs):
        new_minimum = AppVersion.objects.get(
            application=amo.ANDROID.id,
            version=settings.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
        )
        qs = ApplicationsVersions.objects.filter(
            application=amo.ANDROID.id,
            # 119.0a1 is the first version we started to set as the minimum, so
            # that's the first version we'll need to start bumping from, and
            # will remain true in the future, it can be hardcoded.
            min__version_int__gte=version_int('119.0a1'),
        )
        qs.update(min=new_minimum)
