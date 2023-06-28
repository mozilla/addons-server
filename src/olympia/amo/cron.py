import itertools

from datetime import datetime, timedelta
from subprocess import PIPE, Popen

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import connection, IntegrityError

import waffle

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.amo.utils import chunked
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import Collection
from olympia.constants.base import VALID_ADDON_STATUSES, VALID_FILE_STATUSES
from olympia.files.models import FileUpload
from olympia.lib.akismet.models import AkismetReport
from olympia.lib.es.utils import raise_if_reindex_in_progress
from product_details import product_details

from . import tasks

log = olympia.core.logger.getLogger('z.cron')


def add_latest_appversion(test_override_versions = None):
    """Adds the latest Daily app versions of Thunderbird to ATN"""
    version_info = product_details.thunderbird_versions if test_override_versions is None else test_override_versions
    version_key = 'LATEST_THUNDERBIRD_NIGHTLY_VERSION'

    main_version = version_info.get(version_key)
    if not main_version or '.' not in main_version:
        return

    # Grab the major version and generate a `.0` and a `.*` version
    major_number = main_version.split('.')[0]
    if not major_number.isdigit():
        log.debug('[add_latest_appversion] Major version {version} is not a number'.format(version=major_number))
        return

    base_major_version = "{major_number}.0".format(major_number=major_number)
    any_major_version = "{major_number}.*".format(major_number=major_number)

    versions = [main_version, base_major_version, any_major_version]

    for version in versions:
        try:
            AppVersion.objects.create(application=amo.THUNDERBIRD.id, version=version)
        except IntegrityError as e:
            log.debug('[add_latest_appversion] Version {version} already exists: {err}'.format(version=version, err=e))


def gc(test_result=True):
    """Site-wide garbage collections."""
    def days_ago(days):
        return datetime.today() - timedelta(days=days)

    log.debug('Collecting data to delete')

    logs = (ActivityLog.objects.filter(created__lt=days_ago(90))
            .exclude(action__in=amo.LOG_KEEP).values_list('id', flat=True))

    collections_to_delete = (
        Collection.objects.filter(created__lt=days_ago(2),
                                  type=amo.COLLECTION_ANONYMOUS)
        .values_list('id', flat=True))
    akismet_reports_to_delete = (
        AkismetReport.objects.filter(created__lt=days_ago(90))
        .values_list('id', flat=True))

    for chunk in chunked(logs, 100):
        tasks.delete_logs.delay(chunk)
    for chunk in chunked(collections_to_delete, 100):
        tasks.delete_anonymous_collections.delay(chunk)
    for chunk in chunked(akismet_reports_to_delete, 100):
        tasks.delete_akismet_reports.delay(chunk)
    # Incomplete addons cannot be deleted here because when an addon is
    # rejected during a review it is marked as incomplete. See bug 670295.

    log.debug('Cleaning up test results extraction cache.')
    # lol at check for '/'
    if settings.MEDIA_ROOT and settings.MEDIA_ROOT != '/':
        cmd = ('find', settings.MEDIA_ROOT, '-maxdepth', '1', '-name',
               'validate-*', '-mtime', '+7', '-type', 'd',
               '-exec', 'rm', '-rf', "{}", ';')

        output = Popen(cmd, stdout=PIPE).communicate()[0]

        for line in output.split("\n"):
            log.debug(line)

    else:
        log.warning('MEDIA_ROOT not defined.')

    if user_media_path('collection_icons'):
        log.debug('Cleaning up uncompressed icons.')

        cmd = ('find', user_media_path('collection_icons'),
               '-name', '*__unconverted', '-mtime', '+1', '-type', 'f',
               '-exec', 'rm', '{}', ';')
        output = Popen(cmd, stdout=PIPE).communicate()[0]

        for line in output.split("\n"):
            log.debug(line)

    USERPICS_PATH = user_media_path('userpics')
    if USERPICS_PATH:
        log.debug('Cleaning up uncompressed userpics.')

        cmd = ('find', USERPICS_PATH,
               '-name', '*__unconverted', '-mtime', '+1', '-type', 'f',
               '-exec', 'rm', '{}', ';')
        output = Popen(cmd, stdout=PIPE).communicate()[0]

        for line in output.split("\n"):
            log.debug(line)

    # Delete stale FileUploads.
    stale_uploads = FileUpload.objects.filter(
        created__lte=days_ago(180)).order_by('id')
    for file_upload in stale_uploads:
        log.debug(u'[FileUpload:{uuid}] Removing file: {path}'
                  .format(uuid=file_upload.uuid, path=file_upload.path))
        if file_upload.path:
            try:
                storage.delete(file_upload.path)
            except OSError:
                pass
        file_upload.delete()


def category_totals():
    """
    Update category counts for sidebar navigation.
    """
    log.debug('Starting category counts update...')
    addon_statuses = ",".join(['%s'] * len(VALID_ADDON_STATUSES))
    file_statuses = ",".join(['%s'] * len(VALID_FILE_STATUSES))

    with connection.cursor() as cursor:
        cursor.execute("""
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
        """ % (file_statuses, addon_statuses),
            VALID_FILE_STATUSES + VALID_ADDON_STATUSES)


def weekly_downloads():
    """
    Update 7-day add-on download counts.
    """

    if not waffle.switch_is_active('local-statistics-processing'):
        return False

    raise_if_reindex_in_progress('amo')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT addon_id, SUM(count) AS weekly_count
            FROM download_counts
            WHERE `date` >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY addon_id
            ORDER BY addon_id""")
        counts = cursor.fetchall()

    addon_ids = [r[0] for r in counts]

    if not addon_ids:
        return

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, 0
            FROM addons
            WHERE id NOT IN %s""", (addon_ids,))
        counts += cursor.fetchall()

        cursor.execute("""
            CREATE TEMPORARY TABLE tmp_wd
            (addon_id INT PRIMARY KEY, count INT)""")
        cursor.execute('INSERT INTO tmp_wd VALUES %s' %
                       ','.join(['(%s,%s)'] * len(counts)),
                       list(itertools.chain(*counts)))

        cursor.execute("""
            UPDATE addons INNER JOIN tmp_wd
                ON addons.id = tmp_wd.addon_id
            SET weeklydownloads = tmp_wd.count""")
        cursor.execute("DROP TABLE IF EXISTS tmp_wd")
