from datetime import datetime, timedelta
from django.core.files.storage import default_storage as storage
from django.db import connection

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.addons.tasks import delete_addons
from olympia.amo.utils import chunked
from olympia.bandwagon.models import Collection
from olympia.constants.base import VALID_ADDON_STATUSES, VALID_FILE_STATUSES
from olympia.files.models import FileUpload
from olympia.scanners.models import ScannerResult

from . import tasks


log = olympia.core.logger.getLogger('z.cron')


def gc(test_result=True):
    """Site-wide garbage collections."""

    def days_ago(days):
        return datetime.today() - timedelta(days=days)

    log.info('Collecting data to delete')

    logs = (
        ActivityLog.objects.filter(created__lt=days_ago(90))
        .exclude(action__in=amo.LOG_KEEP)
        .values_list('id', flat=True)
    )

    collections_to_delete = Collection.objects.filter(
        created__lt=days_ago(2), type=amo.COLLECTION_ANONYMOUS
    ).values_list('id', flat=True)

    for chunk in chunked(logs, 100):
        tasks.delete_logs.delay(chunk)
    for chunk in chunked(collections_to_delete, 100):
        tasks.delete_anonymous_collections.delay(chunk)

    a_week_ago = days_ago(7)
    # Delete stale add-ons with no versions. Should soft-delete add-ons that
    # are somehow not in incomplete status, hard-delete the rest. No email
    # should be sent in either case.
    versionless_addons = Addon.objects.filter(
        versions__pk=None, created__lte=a_week_ago
    ).values_list('pk', flat=True)
    for chunk in chunked(versionless_addons, 100):
        delete_addons.delay(chunk)

    # Delete stale FileUploads.
    stale_uploads = FileUpload.objects.filter(created__lte=a_week_ago).order_by('id')
    for file_upload in stale_uploads:
        log.info(
            u'[FileUpload:{uuid}] Removing file: {path}'.format(
                uuid=file_upload.uuid, path=file_upload.path
            )
        )
        if file_upload.path:
            try:
                storage.delete(file_upload.path)
            except OSError:
                pass
        file_upload.delete()

    # Delete stale ScannerResults.
    ScannerResult.objects.filter(upload=None, version=None).delete()


def category_totals():
    """
    Update category counts for sidebar navigation.
    """
    log.info('Starting category counts update...')
    addon_statuses = ",".join(['%s'] * len(VALID_ADDON_STATUSES))
    file_statuses = ",".join(['%s'] * len(VALID_FILE_STATUSES))

    with connection.cursor() as cursor:
        cursor.execute(
            """
        UPDATE categories AS t INNER JOIN (
         SELECT at.category_id, COUNT(DISTINCT Addon.id) AS ct
          FROM addons AS Addon
          INNER JOIN versions AS Version
            ON (Addon.id = Version.addon_id)
          INNER JOIN applications_versions AS av
            ON (av.version_id = Version.id)
          INNER JOIN addons_categories AS at
            ON (at.addon_id = Addon.id)
          INNER JOIN files AS File
            ON (Version.id = File.version_id AND File.status IN (%s))
          WHERE Addon.status IN (%s) AND Addon.inactive = 0
          GROUP BY at.category_id)
        AS j ON (t.id = j.category_id)
        SET t.count = j.ct
        """
            % (file_statuses, addon_statuses),
            VALID_FILE_STATUSES + VALID_ADDON_STATUSES,
        )
