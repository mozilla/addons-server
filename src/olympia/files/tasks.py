import json
import os
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import transaction

import waffle

import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import StopWatch
from olympia.devhub.tasks import validation_task
from olympia.files.models import File, FileManifest, FileUpload, WebextPermission
from olympia.files.utils import (
    ManifestJSONExtractor,
    extract_zip,
    get_sha256,
    parse_xpi,
)
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.files.task')


@task
@use_primary_db
def extract_host_permissions(ids, **kw):
    log.info(
        '[%s@%s] Extracting host permissions from Files, from id: %s to id: %s...'
        % (len(ids), extract_host_permissions.rate_limit, ids[0], ids[-1])
    )
    files = File.objects.filter(pk__in=ids).no_transforms()

    # A user needs to be passed down to parse_xpi(), so we use the task user.
    user = UserProfile.objects.get(pk=settings.TASK_USER_ID)

    for file_ in files:
        try:
            log.info('Parsing File.id: %s @ %s' % (file_.pk, file_.file.path))
            parsed_data = parse_xpi(file_.file.path, addon=file_.addon, user=user)
            host_permissions = parsed_data.get('host_permissions', [])
            if host_permissions:
                log.info(
                    'Found %s host permissions for: %s'
                    % (len(host_permissions), file_.pk)
                )
                WebextPermission.objects.update_or_create(
                    defaults={'host_permissions': host_permissions}, file=file_
                )
        except Exception as err:
            log.error('Failed to extract: %s, error: %s' % (file_.pk, err))


@validation_task
def repack_fileupload(results, upload_pk):
    log.info('Starting task to repackage FileUpload %s', upload_pk)
    upload = FileUpload.objects.get(pk=upload_pk)
    # When a FileUpload is created and a file added to it, if it's a xpi/zip,
    # it should be moved to upload.file_path, and it should have a .zip
    # extension, so we only need to care about that extension here.
    # We don't trust upload.name: it's the original filename as used by the
    # developer, so it could be something else.
    if upload.file_path.endswith('.zip'):
        timer = StopWatch('files.tasks.repack_fileupload.')
        timer.start()
        # tempdir must *not* be on TMP_PATH, we want local fs instead. It will be
        # deleted automatically once we exit the context manager.
        with tempfile.TemporaryDirectory(prefix='repack_fileupload_extract') as tempdir:
            # extract_zip can raise an exception for a number of reasons, but
            # @validation_task should catch everything, return a nice error
            # message to the developer and log the exception if it's not
            # something we are handling.
            extract_zip(upload.file_path, tempdir=tempdir)

            if waffle.switch_is_active('enable-manifest-normalization'):
                manifest = Path(tempdir) / 'manifest.json'

                if manifest.exists():
                    try:
                        xpi_data = parse_xpi(upload.file_path, minimal=True)

                        if not xpi_data.get('is_mozilla_signed_extension', False):
                            json_data = ManifestJSONExtractor(
                                manifest.read_bytes()
                            ).data
                            manifest.write_text(json.dumps(json_data, indent=2))
                    except Exception:
                        # If we cannot normalize the manifest file, we skip
                        # this step and let the linter catch the exact
                        # cause in order to return a more appropriate error
                        # than "unexpected error", which would happen if
                        # this task was handling the error itself.
                        pass
            timer.log_interval('1.extracted')
            log.info('Zip from upload %s extracted, repackaging', upload_pk)
            # We'll move the file to its final location below with move_stored_file(),
            # so don't let tempfile delete it.
            file_ = tempfile.NamedTemporaryFile(
                dir=settings.TMP_PATH, suffix='.zip', delete=False
            )
            shutil.make_archive(os.path.splitext(file_.name)[0], 'zip', tempdir)
        upload.hash = 'sha256:%s' % get_sha256(file_)
        timer.log_interval('2.repackaged')
        log.info('Zip from upload %s repackaged, moving file back', upload_pk)
        storage.move_stored_file(file_.name, upload.file_path)
        timer.log_interval('3.moved')
        upload.save()
        timer.log_interval('4.end')
    else:
        log.info('Not repackaging upload %s, it is not a zip file.', upload_pk)
    return results
