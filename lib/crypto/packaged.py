import json
import os
import shutil
import tempfile
import zipfile

from django.conf import settings
from django.core.files.storage import default_storage as storage

from base64 import b64decode
from celeryutils import task
import commonware.log
from django_statsd.clients import statsd
from signing_clients.apps import JarExtractor
import requests

import amo
from versions.models import Version

log = commonware.log.getLogger('z.crypto')


class SigningError(Exception):
    pass


def sign_app(src, dest, ids, reviewer=False):
    """
    Generate a manifest and signature and send signature to signing server to
    be signed.
    """
    active_endpoint = _get_endpoint(reviewer)
    timeout = settings.SIGNED_APPS_SERVER_TIMEOUT

    if not active_endpoint:
        _no_sign(src, dest)
        return

    # Extract necessary info from the archive
    tempf = tempfile.TemporaryFile()
    try:
        jar = JarExtractor(
            storage.open(src, 'r'), tempf,
            ids,
            omit_signature_sections=settings.SIGNED_APPS_OMIT_PER_FILE_SIGS)
    except:
        log.error('Archive extraction failed. Bad archive?', exc_info=True)
        raise SigningError('Archive extraction failed. Bad archive?')

    log.info('App signature contents: %s' % jar.signatures)

    log.info('Calling service: %s' % active_endpoint)
    try:
        with statsd.timer('services.sign.app'):
            response = requests.post(active_endpoint, timeout=timeout,
                                     files={'file': ('zigbert.sf',
                                                     str(jar.signatures))})
    except requests.exceptions.HTTPError, error:
        # Will occur when a 3xx or greater code is returned.
        log.error('Posting to app signing failed: %s, %s' % (
            error.response.status, error))
        raise SigningError('Posting to app signing failed: %s, %s' % (
            error.response.status, error))

    except:
        # Will occur when some other error occurs.
        log.error('Posting to app signing failed', exc_info=True)
        raise SigningError('Posting to app signing failed')

    if response.status_code != 200:
        log.error('Posting to app signing failed: %s' % response.reason)
        raise SigningError('Posting to app signing failed: %s'
                           % response.reason)

    pkcs7 = b64decode(json.loads(response.content)['zigbert.rsa'])
    try:
        jar.make_signed(pkcs7)
    except:
        log.error('App signing failed', exc_info=True)
        raise SigningError('App signing failed')
    with storage.open(dest, 'w') as destf:
        tempf.seek(0)
        shutil.copyfileobj(tempf, destf)

def _get_endpoint(reviewer=False):
    """
    Returns the proper API endpoint depending whether we are signing for
    reviewer or for public consumption.
    """
    active = (settings.SIGNED_APPS_REVIEWER_SERVER_ACTIVE if reviewer else
              settings.SIGNED_APPS_SERVER_ACTIVE)
    server = (settings.SIGNED_APPS_REVIEWER_SERVER if reviewer else
              settings.SIGNED_APPS_SERVER)

    if active:
        if not server:
            # If no API endpoint is set. Just ignore this request.
            raise ValueError(
                'Invalid config. The %sserver setting is empty.' % (
                    'reviewer ' if reviewer else ''))
        return server + '/1.0/sign_app'


def _no_sign(src, dest):
    # If this is a local development instance, just copy the file around
    # so that everything seems to work locally.
    log.info('Not signing the app, no signing server is active.')
    dest_dir = os.path.dirname(dest)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
    shutil.copy(src, dest)


@task
def sign(version_id, reviewer=False, resign=False, **kw):
    version = Version.objects.get(pk=version_id)
    app = version.addon
    log.info('Signing version: %s of app: %s' % (version_id, app))

    if not app.type == amo.ADDON_WEBAPP:
        log.error('[Webapp:%s] Attempt to sign something other than an app.' %
                  app.id)
        raise SigningError('Not an app')

    if not app.is_packaged:
        log.error('[Webapp:%s] Attempt to sign a non-packaged app.' % app.id)
        raise SigningError('Not packaged')

    try:
        file_obj = version.all_files[0]
    except IndexError:
        log.error(
            '[Webapp:%s] Attempt to sign an app with no files in version.' %
            app.id)
        raise SigningError('No file')

    path = (file_obj.signed_reviewer_file_path if reviewer else
            file_obj.signed_file_path)

    if storage.exists(path) and not resign:
        log.info('[Webapp:%s] Already signed app exists.' % app.id)
        return path

    if resign:
        z = zipfile.ZipFile(file_obj.file_path, 'r')
        if 'META-INF/ids.json' in z.namelist():
            # This zip is broken due to previously used bad signing
            # code. rebuild it. (This code can be deleted once all
            # broken packages are re-signed.)
            tempf = tempfile.NamedTemporaryFile(delete=False)
            zout = zipfile.ZipFile(tempf, 'w', zipfile.ZIP_DEFLATED)
            for f in sorted(z.infolist()):
                if f.filename != 'META-INF/ids.json':
                    zout.writestr(f, z.read(f.filename))
            zout.close()
            os.rename(tempf.name, file_obj.file_path)

    ids = json.dumps({
        'id': app.guid,
        'version': version_id
    })
    with statsd.timer('services.sign.app'):
        try:
            sign_app(file_obj.file_path, path, ids, reviewer)
        except SigningError:
            log.info('[Webapp:%s] Signing failed' % app.id)
            if storage.exists(path):
                storage.delete(path)
            raise
    log.info('[Webapp:%s] Signing complete.' % app.id)
    return path
