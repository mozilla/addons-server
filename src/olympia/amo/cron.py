from datetime import datetime, timedelta
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.http import HttpRequest

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.addons.tasks import delete_addons
from olympia.amo.utils import chunked
from olympia.bandwagon.models import Collection
from olympia.files.models import FileUpload
from olympia.scanners.models import ScannerResult

from . import tasks
from .sitemap import build_sitemap, get_sitemap_path, get_sitemap_section_pages


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

    two_weeks_ago = days_ago(15)
    # Delete stale add-ons with no versions. Should soft-delete add-ons that
    # are somehow not in incomplete status, hard-delete the rest. No email
    # should be sent in either case.
    versionless_addons = Addon.objects.filter(
        versions__pk=None, created__lte=two_weeks_ago
    ).values_list('pk', flat=True)
    for chunk in chunked(versionless_addons, 100):
        delete_addons.delay(chunk)

    # Delete stale FileUploads.
    stale_uploads = FileUpload.objects.filter(created__lte=two_weeks_ago).order_by('id')
    for file_upload in stale_uploads:
        log.info(
            '[FileUpload:{uuid}] Removing file: {path}'.format(
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


def _setup_default_prefixer():
    """`reverse` depends on a prefixer being set for an app and/or locale in the url,
    and for non-requests (i.e. cron) this isn't set up."""
    request = HttpRequest()
    request.META['SCRIPT_NAME'] = ''
    prefixer = amo.urlresolvers.Prefixer(request)
    prefixer.app = settings.DEFAULT_APP
    prefixer.locale = settings.LANGUAGE_CODE
    amo.reverse.set_url_prefix(prefixer)


def write_sitemaps():
    _setup_default_prefixer()
    index_url = get_sitemap_path()
    with storage.open(index_url, 'w') as index_file:
        index_file.write(build_sitemap())
    for section, page in get_sitemap_section_pages():
        filename = get_sitemap_path(section, page)
        with storage.open(filename, 'w') as sitemap_file:
            content = build_sitemap(section, page)
            sitemap_file.write(content)
