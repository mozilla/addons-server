import hashlib
import os
import shutil
import tempfile
import zipfile

from base64 import b64decode, b64encode

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils.encoding import force_bytes

import requests

from django_statsd.clients import statsd
from requests_hawk import HawkAuth
from signing_clients.apps import JarExtractor, get_signer_serial_number

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


def get_id(addon):
    """Return the addon GUID if <= 64 chars, or its sha256 hash otherwise.

    We don't want GUIDs longer than 64 chars: bug 1203365.
    """
    guid = addon.guid
    if len(guid) <= 64:
        return guid
    return hashlib.sha256(guid).hexdigest()


def call_signing(file_obj):
    """Get the jar signature and send it to the signing server to be signed."""
    # Extract jar signature.
    jar = JarExtractor(path=storage.open(file_obj.file_path))

    log.debug(u'File signature contents: {0}'.format(jar.signatures))

    signed_manifest = unicode(jar.signatures)

    conf = settings.AUTOGRAPH_CONFIG
    log.debug('Calling autograph service: {0}'.format(conf['server_url']))

    # create the signing request
    signing_request = [{
        'input': b64encode(signed_manifest),
        'keyid': conf['signer'],
        'options': {
            'id': get_id(file_obj.version.addon),
        },
    }]

    # post the request
    with statsd.timer('services.sign.addon.autograph'):
        response = requests.post(
            '{server}/sign/data'.format(server=conf['server_url']),
            json=signing_request,
            auth=HawkAuth(id=conf['user_id'], key=conf['key']))

    if response.status_code != requests.codes.CREATED:
        msg = u'Posting to add-on signing failed: {0} {1}'.format(
            response.reason, response.text)
        log.error(msg)
        raise SigningError(msg)

    # convert the base64 encoded pkcs7 signature back to binary
    pkcs7 = b64decode(force_bytes(response.json()[0]['signature']))

    cert_serial_num = get_signer_serial_number(pkcs7)

    # We only want the (unique) temporary file name.
    with tempfile.NamedTemporaryFile(dir=settings.TMP_PATH) as temp_file:
        temp_filename = temp_file.name

    jar.make_signed(
        signed_manifest=signed_manifest,
        signature=pkcs7,
        sigpath=u'mozilla',
        outpath=temp_filename)
    shutil.move(temp_filename, file_obj.file_path)
    return cert_serial_num


def sign_file(file_obj):
    """Sign a File.

    If there's no endpoint (signing is not enabled) or isn't reviewed yet,
    or there was an error while signing, log and return nothing.

    Otherwise return the signed file.
    """
    if not settings.ENABLE_ADDON_SIGNING:
        log.info(u'Not signing file {0}: no active endpoint'.format(
            file_obj.pk))
        return

    # No file? No signature.
    if not os.path.exists(file_obj.file_path):
        log.info(u'File {0} doesn\'t exist on disk'.format(file_obj.file_path))
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
    cert_serial_num = unicode(call_signing(file_obj))

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
