import json
import os
import shutil
import tempfile
from base64 import b64decode

from django.conf import settings
from django.core.files.storage import default_storage as storage

import commonware.log
import requests
from celeryutils import task
from django_statsd.clients import statsd
from signing_clients.apps import JarExtractor

from versions.models import Version


log = commonware.log.getLogger('z.crypto')


class SigningError(Exception):
    pass


def sign_addon(src, dest, ids, reviewer=False):
    tempname = tempfile.mktemp()
    try:
        return _sign_addon(src, dest, ids, reviewer, tempname)
    finally:
        try:
            os.unlink(tempname)
        except OSError:
            # If the file has already been removed, don't worry about it.
            pass


def _sign_addon(src, dest, ids, reviewer, tempname):
    """
    Generate a manifest and signature and send signature to signing server to
    be signed.
    """
    active_endpoint = _get_endpoint(reviewer)
    timeout = settings.SIGNING_SERVER_TIMEOUT

    if not active_endpoint:
        _no_sign(src, dest)
        return

    # Extract necessary info from the archive
    try:
        jar = JarExtractor(
            storage.open(src, 'r'), tempname, ids,
            omit_signature_sections=settings.SIGNING_OMIT_PER_FILE_SIGS)
    except:
        msg = 'Archive extraction failed. Bad archive?'
        log.error(msg, exc_info=True)
        raise SigningError(msg)

    log.info('Addon signature contents: %s' % jar.signatures)

    log.info('Calling service: %s' % active_endpoint)
    try:
        with statsd.timer('services.sign.app'):
            response = requests.post(active_endpoint, timeout=timeout,
                                     files={'file': ('zigbert.sf',
                                                     str(jar.signatures))})
    except requests.exceptions.HTTPError as error:
        # Will occur when a 3xx or greater code is returned.
        msg = 'Posting to app signing failed: %s, %s'
        log.error(msg % (error.response.status, error))
        raise SigningError(msg % (error.response.status, error))

    except:
        # Will occur when some other error occurs.
        log.error('Posting to app signing failed', exc_info=True)
        raise SigningError('Posting to app signing failed')

    if response.status_code != 200:
        msg = 'Posting to app signing failed: %s'
        log.error(msg % response.reason)
        raise SigningError(msg % response.reason)

    pkcs7 = b64decode(json.loads(response.content)['zigbert.rsa'])
    try:
        jar.make_signed(pkcs7)
    except:
        log.error('Addon signing failed', exc_info=True)
        raise SigningError('Addon signing failed')
    with storage.open(dest, 'w') as destf:
        tempf = open(tempname)
        shutil.copyfileobj(tempf, destf)


def _get_endpoint(reviewer=False):
    """
    Returns the proper API endpoint depending whether we are signing for
    reviewer or for public consumption.
    """
    active = (settings.SIGNING_REVIEWER_SERVER_ACTIVE if reviewer else
              settings.SIGNING_SERVER_ACTIVE)
    server = (settings.SIGNING_REVIEWER_SERVER if reviewer else
              settings.SIGNING_SERVER)

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
    log.info('Not signing the addon, no signing server is active.')
    dest_dir = os.path.dirname(dest)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
    shutil.copy(src, dest)


def _sign_file(version_id, addon, file_obj, reviewer, resign):
    path = (file_obj.signed_reviewer_file_path if reviewer else
            file_obj.signed_file_path)

    if not file_obj.can_be_signed():
        log.error('[Addon:%s] Attempt to sign a non-xpi file.' % addon.id)
        raise SigningError('Non XPI')

    if storage.exists(path) and not resign:
        log.info('[Addon:%s] Already signed addon exists.' % addon.id)
        return path

    if reviewer:
        # Reviewers get a unique 'id' so the reviewer installed addon won't
        # conflict with the public addon, and also so multiple versions of the
        # same addon won't conflict with themselves.
        ids = json.dumps({
            'id': 'reviewer-%s-%s' % (addon.guid, version_id),
            'version': version_id
        })
    else:
        ids = json.dumps({
            'id': addon.guid,
            'version': version_id
        })
    with statsd.timer('services.sign.app'):
        try:
            sign_addon(file_obj.file_path, path, ids, reviewer)
        except SigningError:
            log.info('[Addon:%s] Signing failed' % addon.id)
            if storage.exists(path):
                storage.delete(path)
            raise
    log.info('[Addon:%s] Signing complete.' % addon.id)
    return path


@task
def sign(version_id, reviewer=False, resign=False, **kw):
    try:
        version = Version.objects.get(pk=version_id)
    except Version.DoesNotExist:
        log.error('Addon version %s does not exist.' % version_id)
        raise SigningError('Version does not exist.')

    addon = version.addon
    log.info('Signing version: %s of addon: %s' % (version_id, addon))

    if not version.all_files:
        log.error(
            '[Addon:%s] Attempt to sign an addon with no files in version.' %
            addon.id)
        raise SigningError('No file')

    path_list = []
    for file_obj in [x for x in version.all_files if x.can_be_signed()]:
        path_list.append((
            file_obj.pk,
            _sign_file(version_id, addon, file_obj, reviewer, resign)
        ))

    return path_list
