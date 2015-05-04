import json
import tempfile
import shutil
import zipfile
from base64 import b64decode

from django.conf import settings
from django.core.files.storage import default_storage as storage

import commonware.log
import requests
from django_statsd.clients import statsd
from signing_clients.apps import get_signature_serial_number, JarExtractor

import amo

log = commonware.log.getLogger('z.crypto')


class SigningError(Exception):
    pass


def get_endpoint(file_obj):
    """Get the endpoint to sign the file, depending on its review status."""
    server = settings.SIGNING_SERVER
    if file_obj.version.addon.status != amo.STATUS_PUBLIC:
        server = settings.PRELIMINARY_SIGNING_SERVER
    if not server:
        return

    return '{server}/1.0/sign_addon'.format(server=server)


def call_signing(file_obj, endpoint):
    """Get the jar signature and send it to the signing server to be signed."""
    # We only want the (unique) temporary file name.
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_filename = temp_file.name

    # Extract jar signature.
    jar = JarExtractor(path=storage.open(file_obj.file_path),
                       outpath=temp_filename,
                       omit_signature_sections=True,
                       extra_newlines=True)

    log.debug('File signature contents: {0}'.format(jar.signatures))

    addon_id = file_obj.version.addon.guid

    log.debug('Calling signing service: {0}'.format(endpoint))
    with statsd.timer('services.sign.addon'):
        response = requests.post(endpoint,
                                 timeout=settings.SIGNING_SERVER_TIMEOUT,
                                 data={'addon_id': addon_id},
                                 files={'file': ('mozilla.sf',
                                                 str(jar.signatures))})
    if response.status_code != 200:
        msg = 'Posting to add-on signing failed: {0}'.format(response.reason)
        log.error(msg)
        raise SigningError(msg)

    pkcs7 = b64decode(json.loads(response.content)['mozilla.rsa'])
    cert_serial_num = get_signature_serial_number(pkcs7)
    jar.make_signed(pkcs7, sigpath='mozilla')
    shutil.move(temp_filename, file_obj.file_path)
    return cert_serial_num


def sign_file(file_obj):
    """Sign a File.

    If there's no endpoint (signing is not enabled), or the file is a hotfix,
    or isn't reviewed yet, or there was an error while signing, log and return
    nothing.

    Otherwise return the signed file.
    """
    endpoint = get_endpoint(file_obj)
    if not endpoint:  # Signing not enabled.
        log.info('Not signing file {0}: no active endpoint'.format(
            file_obj.pk))
        return

    # Don't sign hotfixes.
    if file_obj.version.addon.guid in settings.HOTFIX_ADDON_GUIDS:
        log.info('Not signing file {0}: addon is a hotfix'.format(file_obj.pk))
        return

    # We only sign files that have been reviewed.
    if file_obj.status not in amo.REVIEWED_STATUSES:
        log.info("Not signing file {0}: it isn't reviewed".format(file_obj.pk))
        return

    # Sign the file. If there's any exception, we skip the rest.
    cert_serial_num = call_signing(file_obj, endpoint)  # Sign file.

    # Save the certificate serial number for revocation if needed, and re-hash
    # the file now that it's been signed.
    file_obj.update(cert_serial_num=cert_serial_num,
                    hash=file_obj.generate_hash(),
                    is_signed=True)
    log.info('Signing complete for file {0}'.format(file_obj.pk))
    return file_obj


def is_signed(file_path):
    """Return True if the file has been signed.

    This utility function will help detect if a XPI file has been signed by
    mozilla (if we can't trust the File.is_signed field).

    It will simply check the signature filenames, and assume that if they're
    named "mozilla.*" then the xpi has been signed by us.

    This is in no way a perfect or correct solution, it's just the way we
    do it until we decide to inspect/walk the certificates chain to
    validate it comes from Mozilla.
    """
    try:
        with zipfile.ZipFile(file_path, mode='r') as zf:
            filenames = set(zf.namelist())
    except (zipfile.BadZipfile, IOError):
        filenames = set()
    return set(['META-INF/mozilla.rsa', 'META-INF/mozilla.sf',
                'META-INF/manifest.mf']).issubset(filenames)
