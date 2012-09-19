from django.core.files.storage import default_storage as storage

from celeryutils import task
import commonware.log

import amo
from versions.models import Version

log = commonware.log.getLogger('z.crypto')


class SigningError(Exception):
    pass


@task
def sign(version_id, reviewer=False):
    version = Version.objects.get(pk=version_id)
    app = version.addon
    log.info('Signing version: %s of app: %s' % (version_id, app))

    if not app.type == amo.ADDON_WEBAPP:
        log.error('Attempt to sign something other than an app.')
        raise SigningError('Not an app')

    if not app.is_packaged:
        log.error('Attempt to sign a non-packaged app.')
        raise SigningError('Not packaged')

    try:
        file_obj = version.all_files[0]
    except IndexError:
        log.error('Attempt to sign an app with no files in version.')
        raise SigningError('No file')

    path = (file_obj.signed_reviewer_file_path if reviewer else
            file_obj.signed_file_path)
    if storage.exists(path):
        log.info('Already signed app exists.')
        return path

    # When we know how to sign, we will sign. For the moment, let's copy.
    dest = storage.open(path, 'w')
    src = storage.open(file_obj.file_path, 'r')
    # I'm not sure if this makes sense with an S3 backend.
    while 1:
        buffer = src.read(1024 * 1024)
        if buffer:
            dest.write(buffer)
        else:
            break

    dest.close()
    src.close()
    log.info('Signing complete.')
    return path
