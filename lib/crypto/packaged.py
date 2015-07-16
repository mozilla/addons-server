import glob
import json
import os
import shutil
import tempfile
import zipfile
from base64 import b64decode

from django.conf import settings
from django.core.files.storage import default_storage as storage

import commonware.log
import requests
from django_statsd.clients import statsd
from signing_clients.apps import get_signature_serial_number, JarExtractor

import amo
from files.utils import extract_xpi, parse_xpi
from versions.compare import version_int

log = commonware.log.getLogger('z.crypto')


class SigningError(Exception):
    pass


def supports_firefox(file_obj):
    """Return True if the file support a high enough version of Firefox.

    We only sign files that are at least compatible with Firefox
    MIN_NOT_D2C_VERSION, or Firefox MIN_NOT_D2C_VERSION if they are not default
    to compatible.
    """
    apps = file_obj.version.apps.all()
    if not file_obj.binary_components and not file_obj.strict_compatibility:
        # Version is "default to compatible".
        return apps.filter(
            max__application=amo.FIREFOX.id,
            max__version_int__gte=version_int(settings.MIN_D2C_VERSION))
    else:
        # Version isn't "default to compatible".
        return apps.filter(
            max__application=amo.FIREFOX.id,
            max__version_int__gte=version_int(settings.MIN_NOT_D2C_VERSION))


def get_endpoint(server):
    """Get the endpoint to sign the file, either the full or prelim one."""
    if not server:  # Setting is empty, signing isn't enabled.
        return

    return u'{server}/1.0/sign_addon'.format(server=server)


def call_signing(file_path, endpoint, guid):
    """Get the jar signature and send it to the signing server to be signed."""
    # We only want the (unique) temporary file name.
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_filename = temp_file.name

    # Extract jar signature.
    jar = JarExtractor(path=storage.open(file_path),
                       outpath=temp_filename,
                       omit_signature_sections=True,
                       extra_newlines=True)

    log.debug(u'File signature contents: {0}'.format(jar.signatures))

    log.debug(u'Calling signing service: {0}'.format(endpoint))
    with statsd.timer('services.sign.addon'):
        response = requests.post(endpoint,
                                 timeout=settings.SIGNING_SERVER_TIMEOUT,
                                 data={'addon_id': guid},
                                 files={'file': (u'mozilla.sf',
                                                 unicode(jar.signatures))})
    if response.status_code != 200:
        msg = u'Posting to add-on signing failed: {0}'.format(response.reason)
        log.error(msg)
        raise SigningError(msg)

    pkcs7 = b64decode(json.loads(response.content)['mozilla.rsa'])
    cert_serial_num = get_signature_serial_number(pkcs7)
    jar.make_signed(pkcs7, sigpath=u'mozilla')
    shutil.move(temp_filename, file_path)
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

    # We only sign files that are compatible with Firefox.
    if not supports_firefox(file_obj):
        log.info(
            u'Not signing version {0}: not for a Firefox version we support'
            .format(file_obj.version.pk))
        return

    guid = file_obj.version.addon.guid

    if file_obj.is_multi_package:
        # We need to sign all the internal extensions, if any.
        cert_serial_num = sign_multi(file_obj.file_path, endpoint, guid)
        if not cert_serial_num:  # There was no internal extensions to sign.
            return
    else:
        # Sign the file. If there's any exception, we skip the rest.
        cert_serial_num = unicode(call_signing(
            file_obj.file_path, endpoint, guid))

    # Save the certificate serial number for revocation if needed, and re-hash
    # the file now that it's been signed.
    file_obj.update(cert_serial_num=cert_serial_num,
                    hash=file_obj.generate_hash(),
                    is_signed=True)
    log.info(u'Signing complete for file {0}'.format(file_obj.pk))
    return file_obj


def sign_multi(file_path, endpoint, guid):
    """Sign the internal extensions from a multi-package XPI (if any)."""
    log.info('Signing multi-package file {0}'.format(file_path))
    # Extract the multi-package to a temp folder.
    folder = tempfile.mkdtemp()
    try:
        extract_xpi(file_path, folder)
        xpis = glob.glob(os.path.join(folder, u'*.xpi'))
        cert_serial_nums = []  # The certificate serial numbers for the XPIs.
        for xpi in xpis:
            xpi_info = parse_xpi(xpi, check=False)
            if xpi_info['type'] == amo.ADDON_EXTENSION:
                # Sign the internal extensions in place.
                cert_serial_nums.append(call_signing(xpi, endpoint, guid))
        # Repackage (re-zip) the multi-package.
        # We only want the (unique) temporary file name.
        with tempfile.NamedTemporaryFile() as temp_file:
            temp_filename = temp_file.name
        shutil.make_archive(temp_filename, format='zip', root_dir=folder)
        # Now overwrite the current multi-package xpi with the repackaged one.
        # Note that shutil.make_archive automatically added a '.zip' to the end
        # of the base_name provided as first argument.
        shutil.move(u'{0}.zip'.format(temp_filename), file_path)
        return u'\n'.join([unicode(num) for num in cert_serial_nums])
    finally:
        amo.utils.rm_local_tmp_dir(folder)


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
