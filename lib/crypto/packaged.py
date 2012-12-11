import os
import shutil

from django.conf import settings
from django.core.files.storage import default_storage as storage

from base64 import b64decode
from celeryutils import task
import commonware.log
from django_statsd.clients import statsd
import json
from signing_clients.apps import JarExtractor
import requests

import amo
from versions.models import Version

log = commonware.log.getLogger('z.crypto')


class SigningError(Exception):
    pass


def sign_app(src, dest):
    """
    Generate a manifest and signature andend signature to signing server to be
    signed.
    """
    if settings.SIGNED_APPS_SERVER_ACTIVE:
        # If no API endpoint is set. Just ignore this request.
        if not settings.SIGNED_APPS_SERVER:
            raise ValueError('Invalid config. SIGNED_APPS_SERVER empty.')

        endpoint = settings.SIGNED_APPS_SERVER + '/1.0/sign_app'
        timeout = settings.SIGNED_APPS_SERVER_TIMEOUT

        # Extract necessary info from the archive
        try:
            jar = JarExtractor(storage.open(src, 'r'), storage.open(dest, 'w'),
                               omit_signature_sections=
                                   settings.SIGNED_APPS_OMIT_PER_FILE_SIGS)
        except:
            log.error("Archive extraction failed. Bad archive?", exc_info=True)
            raise SigningError("Archive extraction failed. Bad archive?")

        log.info('App signature contents: %s' % jar.signatures)

        log.info('Calling service: %s' % endpoint)
        try:
            with statsd.timer('services.sign.app'):
                response = requests.post(endpoint, timeout=timeout,
                                         files={'file': ('zigbert.sf',
                                                         str(jar.signatures))})
        except requests.exceptions.HTTPError, error:
            # Will occur when a 3xx or greater code is returned.
            log.error('Posting to app signing failed: %s, %s'
                      % (error.response.status, error))
            raise SigningError('Posting to app signing failed: %s, %s'
                               % (error.response.status, error))

        except:
            # Will occur when some other error occurs.
            log.error('Posting to app signing failed', exc_info=True)
            raise SigningError('Posting to app signing failed')

        if response.status_code != 200:
            log.error('Posting to app signing failed: %s'
                      % response.reason)
            raise SigningError('Posting to app signing failed: %s'
                               % response.reason)

        pkcs7 = b64decode(json.loads(response.content)['zigbert.rsa'])
        try:
            jar.make_signed(pkcs7)
        except:
            log.error("App signing failed", exc_info=True)
            raise SigningError("App signing failed")

        return

    else:
        # If this is a local development instance, just copy the file around
        # so that everything seems to work locally.
        log.info('Not signing the app, no signing server is active.')
        dest_dir = os.path.dirname(dest)
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        shutil.copy(src, dest)
        return


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
        try:
            sign_app(file_obj.file_path, path)
        except SigningError:
            if storage.exists(path):
                storage.delete(path)
            raise
    log.info('Signing complete.')
    return path
