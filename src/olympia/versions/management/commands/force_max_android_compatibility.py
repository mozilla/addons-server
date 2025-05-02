from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.db.transaction import atomic

import olympia.core.logger
from olympia import amo
from olympia.applications.models import AppVersion
from olympia.constants.promoted import PROMOTED_GROUPS
from olympia.files.models import File
from olympia.versions.models import ApplicationsVersions


log = olympia.core.logger.getLogger('z.versions.force_max_android_compatibility')


class Command(BaseCommand):
    """
    Force *all* versions of add-ons compatible with Firefox for Android with a
    minimum version lower than <MIN_VERSION_FENIX_GENERAL_AVAILABILITY> and not
    recommended or line for Android to have a max version of 68.*, or to have
    their compatibility with Firefox for Android dropped it their min was
    higher than 68.* already.
    """

    help = (
        'Force add-ons not already compatible with '
        f'{amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY} and higher to be '
        'compatible with Firefox for Android 68.* or lower'
    )

    def handle(self, *args, **kwargs):
        min_version_fenix = AppVersion.objects.get(
            application=amo.ANDROID.id,
            version=amo.MIN_VERSION_FENIX_GENERAL_AVAILABILITY,
        )
        max_version_fennec = AppVersion.objects.get(
            application=amo.ANDROID.id, version=amo.MAX_VERSION_FENNEC
        )
        promoted_groups_ids = [
            p.id for p in PROMOTED_GROUPS if p.can_be_compatible_with_all_fenix_versions
        ]
        qs = (
            # We only care about listed extensions already marked as compatible
            # for Android.
            ApplicationsVersions.objects.filter(application=amo.ANDROID.id)
            .filter(version__addon__type=amo.ADDON_EXTENSION)
            .filter(version__channel=amo.CHANNEL_LISTED)
            .annotate(
                promoted_count=Count('version__addon__promotedaddon')
            )  # force group by
            .filter(
                # They need to be either:
                Q(version__addon__promotedaddon__isnull=True)  # Not promoted at all
                | ~Q(
                    version__addon__promotedaddon__promoted_group__group_id__in=promoted_groups_ids
                )  # Promoted, but not for line / recommended
                | Q(
                    Q(version__addon__promotedaddon__application_id=amo.FIREFOX.id)
                    & ~Q(version__addon__promotedaddon__application_id=amo.ANDROID.id)
                )  # Promoted, but for Firefox only (not Android / not both)
            )
            # If they are already marked as compatible with GA version, we
            # don't care.
            .filter(min__version_int__lt=min_version_fenix.version_int)
        )
        # If the min is also over 68.* then it means the developer marked it
        # as compatible with Fenix only but that's unlikely to be correct, so
        # we drop that compatibility information completely.
        qs_to_drop = qs.filter(min__version_int__gt=max_version_fennec.version_int)
        # Otherwise we'll update it, setting the max to 68.*.
        qs_to_update = qs.exclude(min__version_int__gte=max_version_fennec.version_int)
        with atomic():
            count_versions_compat_updated = qs_to_update.update(
                max=max_version_fennec,
                originated_from=amo.APPVERSIONS_ORIGINATED_FROM_MIGRATION,
            )
        with atomic():
            count_versions_compat_dropped, _ = qs_to_drop.delete()
        with atomic():
            count_files = File.objects.filter(
                version__apps__application=amo.ANDROID.id,
                version__apps__max__version=max_version_fennec,
            ).update(strict_compatibility=True)
        log.info(
            'Done forcing max Android compatibility: '
            'Dropped compat on %d versions, '
            'Updated compat for %d versions, '
            'Set strict compatibility on %d files',
            count_versions_compat_dropped,
            count_versions_compat_updated,
            count_files,
        )
