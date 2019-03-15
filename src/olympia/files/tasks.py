import os
import shutil
import tempfile

from django.conf import settings

import olympia.core.logger

from olympia import amo
from olympia.amo.celery import task
from olympia.amo.decorators import use_primary_db
from olympia.amo.storage_utils import move_stored_file
from olympia.files.models import File, FileUpload, WebextPermission
from olympia.files.utils import extract_zip, get_sha256, parse_xpi
from olympia.users.models import UserProfile


log = olympia.core.logger.getLogger('z.files.task')


@task
@use_primary_db
def extract_webext_permissions(ids, **kw):
    log.info('[%s@%s] Extracting permissions from Files, starting at id: %s...'
             % (len(ids), extract_webext_permissions.rate_limit, ids[0]))
    files = File.objects.filter(pk__in=ids).no_transforms()

    # A user needs to be passed down to parse_xpi(), so we use the task user.
    user = UserProfile.objects.get(pk=settings.TASK_USER_ID)

    for file_ in files:
        try:
            log.info('Parsing File.id: %s @ %s' %
                     (file_.pk, file_.current_file_path))
            parsed_data = parse_xpi(file_.current_file_path, user=user)
            permissions = parsed_data.get('permissions', [])
            # Add content_scripts host matches too.
            for script in parsed_data.get('content_scripts', []):
                permissions.extend(script.get('matches', []))
            if permissions:
                log.info('Found %s permissions for: %s' %
                         (len(permissions), file_.pk))
                WebextPermission.objects.update_or_create(
                    defaults={'permissions': permissions}, file=file_)
        except Exception as err:
            log.error('Failed to extract: %s, error: %s' % (file_.pk, err))


@task
@use_primary_db
def repack_fileupload(upload_pk):
    log.info('Starting task to repackage FileUpload %s', upload_pk)
    upload = FileUpload.objects.get(pk=upload_pk)
    # When a FileUpload is created and a file added to it, if it's a xpi/zip,
    # it should be move to upload.path, and it should have a .xpi extension,
    # so we only need to care about that extension here.
    if upload.path.endswith('.xpi'):
        try:
            tempdir = extract_zip(upload.path)
        except Exception:
            # Something bad happened, maybe we couldn't parse the zip file.
            # This task should have a on_error attached when called by
            # Validator(), so we can just raise and the developer will get a
            # generic error message.
            log.exception('Could not extract upload %s for repack.', upload_pk)
            raise
        log.info('Zip from upload %s extracted, repackaging', upload_pk)
        file_ = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
        shutil.make_archive(os.path.splitext(file_.name)[0], 'zip', tempdir)
        with open(file_.name, 'rb') as f:
            upload.hash = get_sha256(f)
        log.info('Zip from upload %s repackaged, moving file back', upload_pk)
        move_stored_file(file_.name, upload.path)
        upload.save()
    else:
        log.info('Not repackaging upload %s, it is not a xpi file.', upload_pk)
