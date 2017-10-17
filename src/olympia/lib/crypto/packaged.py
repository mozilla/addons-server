import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from base64 import b64decode

from django.conf import settings
from django.core.files.storage import default_storage as storage

import requests
from django_statsd.clients import statsd
from signing_clients.apps import get_signer_serial_number, JarExtractor

import olympia.core.logger
from olympia import amo

log = olympia.core.logger.getLogger('z.crypto')


SIGN_FOR_APPS = (amo.FIREFOX.id, amo.ANDROID.id)


class SigningError(Exception):
    pass


def supports_firefox(file_obj):
    """Return True if the file supports Firefox or Firefox for Android.

    We only sign files that are at least compatible with Firefox/Firefox for
    Android.
    """
    apps = file_obj.version.apps.all()
    return apps.filter(max__application__in=SIGN_FOR_APPS)


def get_endpoint(server):
    """Get the endpoint to sign the file."""
    if not server:  # Setting is empty, signing isn't enabled.
        return

    return u'{server}/1.0/sign_addon'.format(server=server)


def get_id(addon):
    """Return the addon GUID if <= 64 chars, or its sha256 hash otherwise.

    We don't want GUIDs longer than 64 chars: bug 1203365.
    """
    guid = addon.guid
    if len(guid) <= 64:
        return guid
    return hashlib.sha256(guid).hexdigest()


def call_signing(file_obj, endpoint):
    """Get the jar signature and send it to the signing server to be signed."""
    # Extract jar signature.
    jar = JarExtractor(path=storage.open(file_obj.file_path))

    log.debug(u'File signature contents: {0}'.format(jar.signatures))

    log.debug(u'Calling signing service: {0}'.format(endpoint))
    with statsd.timer('services.sign.addon'):
        response = requests.post(
            endpoint,
            timeout=settings.SIGNING_SERVER_TIMEOUT,
            data={'addon_id': get_id(file_obj.version.addon)},
            files={'file': (u'mozilla.sf', unicode(jar.signatures))})
    if response.status_code != 200:
        msg = u'Posting to add-on signing failed: {0}'.format(response.reason)
        log.error(msg)
        raise SigningError(msg)

    pkcs7 = b64decode(json.loads(response.content)['mozilla.rsa'])
    cert_serial_num = get_signer_serial_number(pkcs7)

    # We only want the (unique) temporary file name.
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_filename = temp_file.name

    jar.make_signed(
        signed_manifest=unicode(jar.signatures),
        signature=pkcs7,
        sigpath=u'mozilla',
        outpath=temp_filename)
    shutil.move(temp_filename, file_obj.file_path)
    return cert_serial_num


def sign_file(file_obj, server):
    """Sign a File.

    If there's no endpoint (signing is not enabled), or the file is a hotfix,
    or isn't reviewed yet, or there was an error while signing, log and return
    nothing.

    Otherwise return the signed file.
    """
    endpoint = get_endpoint(server)
    if not endpoint:  # Signing not enabled.
        log.info(u'Not signing file {0}: no active endpoint'.format(
            file_obj.pk))
        return

    # No file? No signature.
    if not os.path.exists(file_obj.file_path):
        log.info(u'File {0} doesn\'t exist on disk'.format(file_obj.file_path))
        return

    # Don't sign hotfixes.
    if file_obj.version.addon.guid in settings.HOTFIX_ADDON_GUIDS:
        log.info(u'Not signing file {0}: addon is a hotfix'.format(
            file_obj.pk))
        return

    # Don't sign Mozilla signed extensions (they're already signed).
    if file_obj.is_mozilla_signed_extension:
        log.info(u'Not signing file {0}: mozilla signed extension is already '
                 u'signed'.format(file_obj.pk))
        return

    # Don't sign multi-package XPIs. Their inner add-ons need to be signed.
    if file_obj.is_multi_package:
        log.info(u'Not signing file {0}: multi-package XPI'.format(
            file_obj.pk))
        return

    # We only sign files that are compatible with Firefox.
    if not supports_firefox(file_obj):
        log.info(
            u'Not signing version {0}: not for a Firefox version we support'
            .format(file_obj.version.pk))
        return

    # Sign the file. If there's any exception, we skip the rest.
    cert_serial_num = unicode(call_signing(file_obj, endpoint))

    size = storage.size(file_obj.file_path)
    # Save the certificate serial number for revocation if needed, and re-hash
    # the file now that it's been signed.
    file_obj.update(cert_serial_num=cert_serial_num,
                    hash=file_obj.generate_hash(),
                    is_signed=True,
                    size=size)
    log.info(u'Signing complete for file {0}'.format(file_obj.pk))
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
    return set([u'META-INF/mozilla.rsa', u'META-INF/mozilla.sf',
                u'META-INF/manifest.mf']).issubset(filenames)
