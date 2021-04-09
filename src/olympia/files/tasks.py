import os
import shutil
import tempfile

import olympia.core.logger

from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.storage_utils import move_stored_file
from olympia.devhub.tasks import validation_task
from olympia.files.models import File, FileUpload
from olympia.files.utils import extract_zip, get_sha256


log = olympia.core.logger.getLogger('z.files.task')


@validation_task
def repack_fileupload(results, upload_pk):
    log.info('Starting task to repackage FileUpload %s', upload_pk)
    upload = FileUpload.objects.get(pk=upload_pk)
    # When a FileUpload is created and a file added to it, if it's a xpi/zip,
    # it should be move to upload.path, and it should have a .xpi extension,
    # so we only need to care about that extension here.
    # We don't trust upload.name: it's the original filename as used by the
    # developer, so it could be something else.
    if upload.path.endswith('.xpi'):
        # tempdir must *not* be on TMP_PATH, we want local fs instead. It will be
        # deleted automatically once we exit the context manager.
        with tempfile.TemporaryDirectory(prefix='repack_fileupload_extract') as tempdir:
            try:
                extract_zip(upload.path, tempdir=tempdir)
            except Exception as exc:
                # Something bad happened, maybe we couldn't parse the zip file.
                # @validation_task should ensure the exception is caught and
                # transformed in a generic error message for the developer, so we
                # just log it and re-raise.
                log.exception(
                    'Could not extract upload %s for repack.', upload_pk, exc_info=exc
                )
                raise
            log.info('Zip from upload %s extracted, repackaging', upload_pk)
            # We'll move the file to its final location below with move_stored_file(),
            # so don't let tempfile delete it.
            file_ = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
            shutil.make_archive(os.path.splitext(file_.name)[0], 'zip', tempdir)
        with open(file_.name, 'rb') as f:
            upload.hash = 'sha256:%s' % get_sha256(f)
        log.info('Zip from upload %s repackaged, moving file back', upload_pk)
        move_stored_file(file_.name, upload.path)
        upload.save()
    else:
        log.info('Not repackaging upload %s, it is not a xpi file.', upload_pk)
    return results


@task
@use_primary_db
def hide_disabled_files(addon_id):
    for file_ in File.objects.filter(version__addon=addon_id):
        file_.hide_disabled_file()
