import json
import os
import tempfile
from base64 import b64decode

from django.conf import settings
from django.core.files.storage import default_storage as storage

import commonware.log
import requests
from celeryutils import task
from django_statsd.clients import statsd
from signing_clients.apps import JarExtractor


log = commonware.log.getLogger('z.crypto')


class SigningError(Exception):
    pass


def call_signing(file_obj):
    """Get the jar signature and send it to the signing server to be signed."""
    if not settings.SIGNING_SERVER:
        log.warning('Not signing: no active endpoint')
        return
    endpoint = '{server}/1.0/sign_addon'.format(server=settings.SIGNING_SERVER)

    timeout = settings.SIGNING_SERVER_TIMEOUT

    # We only want the (unique) temporary file name.
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_filename = temp_file.name

    # Extract jar signature.
    try:
        jar = JarExtractor(path=storage.open(file_obj.file_path),
                           outpath=temp_filename,
                           omit_signature_sections=True)
    except:
        msg = 'Archive extraction failed. Bad archive?'
        log.error(msg, exc_info=True)
        raise SigningError(msg)

    log.info('File signature contents: %s' % jar.signatures)

    # From https://wiki.mozilla.org/AMO/SigningService/API:
    # "A unique identifier for the combination of addon name and version that
    # will be used in the generated key and certificate. A strong preference
    # for human readable.
    addon_id = u"{slug}-{version}".format(slug=file_obj.version.addon.slug,
                                          version=file_obj.version.version)

    log.info('Calling signing service: %s' % endpoint)
    try:
        with statsd.timer('services.sign.addon'):
            response = requests.post(endpoint, timeout=timeout,
                                     data={'addon_id': addon_id},
                                     files={'file': ('zigbert.sf',
                                                     str(jar.signatures))})
    except requests.exceptions.HTTPError as error:
        # Will occur when a 3xx or greater code is returned.
        msg = 'Posting to add-on signing failed: %s, %s' % (
            error.response.status, error)
        log.error(msg)
        raise SigningError(msg)
    except:
        # Will occur when some other error occurs.
        msg = 'Posting to add-on signing failed'
        log.error(msg, exc_info=True)
        raise SigningError(msg)
    if response.status_code != 200:
        msg = 'Posting to add-on signing failed %s' % response.reason
        log.error(msg)
        raise SigningError(msg)

    pkcs7 = b64decode(json.loads(response.content)['zigbert.rsa'])
    try:
        jar.make_signed(pkcs7)
    except:
        msg = 'Addon signing failed'
        log.error(msg, exc_info=True)
        raise SigningError(msg)
    os.rename(temp_filename, file_obj.file_path)
    return True


def sign_file(file_obj):
    if not file_obj.can_be_signed():
        msg = 'Attempt to sign a non-xpi file %s.' % file_obj.pk
        log.error(msg)
        raise SigningError(msg)

    try:
        call_signing(file_obj)
    except SigningError:
        log.info('Signing failed for file %s.' % file_obj.pk)
        raise
    log.info('Signing complete for file %s.' % file_obj.pk)


@task
def sign(version):
    if not version.all_files:
        log.error(
            'Attempt to sign version %s with no files.' % version.pk)
        raise SigningError('No file')

    log.info('Signing version: %s' % version.pk)

    for file_obj in [x for x in version.all_files if x.can_be_signed()]:
        with statsd.timer('services.sign.addon'):
            sign_file(file_obj)
