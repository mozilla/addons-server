import os
import shutil

from django.conf import settings
from django.core.files.storage import default_storage as storage

from celeryutils import task
import commonware.log
from django_statsd.clients import statsd
from xpisign import xpisign

import amo
from versions.models import Version

log = commonware.log.getLogger('z.crypto')


class SigningError(Exception):
    pass


def sign_app(src, dest):
    if settings.SIGNED_APPS_SERVER_ACTIVE:
        # At some point this will be implemented, but not now.
        raise NotImplementedError

    if not os.path.exists(settings.SIGNED_APPS_KEY):
        # TODO: blocked on bug 793876
        # This is a temporary copy that will be unsigned and ignores storage
        # etc.
        # raise ValueError('The signed apps key cannot be found.')
        dest_dir = os.path.dirname(dest)
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        shutil.copy(src, dest)
        return

    # TODO: stop doing this and use the signing server.
    try:
        # Not sure this will work too well on S3.
        xpisign(storage.open(src, 'r'), settings.SIGNED_APPS_KEY,
                storage.open(dest, 'w'))
    except:
        # TODO: figure out some likely errors that can occur.
        log.error('Signing failed', exc_info=True)
        raise


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
    with statsd.timer('services.sign.app'):
        sign_app(file_obj.file_path, path)
    log.info('Signing complete.')
    return path
