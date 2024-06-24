import hashlib
import io
import json
import os
import zipfile
from base64 import b64decode, b64encode

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage as storage
from django.db import transaction
from django.utils.encoding import force_bytes, force_str

import requests
import waffle
from asn1crypto import cms
from django_statsd.clients import statsd
from requests_hawk import HawkAuth

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
    guid = force_bytes(addon.guid)
    if len(guid) <= 64:
        # Return guid as original unicode string.
        return addon.guid
    return force_str(hashlib.sha256(guid).hexdigest())


def use_promoted_signer(file_obj, promo_group):
    return (
        file_obj.version.channel == amo.CHANNEL_LISTED
        and promo_group.autograph_signing_states
    )


def add_guid(file_obj):
    with storage.open(file_obj.file.path) as fobj:
        # Get the file data and add the guid to the manifest.
        with zipfile.ZipFile(fobj, mode='r') as existing_zip:
            manifest_json = json.loads(existing_zip.read('manifest.json'))
            if 'browser_specific_settings' not in manifest_json and manifest_json.get(
                'applications', {}
            ).get('gecko'):
                gecko_root = manifest_json['applications']['gecko']
            else:
                if 'browser_specific_settings' not in manifest_json:
                    manifest_json['browser_specific_settings'] = {}
                if 'gecko' not in manifest_json['browser_specific_settings']:
                    manifest_json['browser_specific_settings']['gecko'] = {}
                gecko_root = manifest_json['browser_specific_settings']['gecko']

            if 'id' not in gecko_root:
                gecko_root['id'] = file_obj.version.addon.guid
                new_zip_buffer = io.BytesIO()
                with zipfile.ZipFile(new_zip_buffer, mode='w') as new_zip:
                    for info in existing_zip.filelist:
                        if info.filename == 'manifest.json':
                            new_zip.writestr(
                                'manifest.json',
                                json.dumps(manifest_json, indent=2).encode('utf-8'),
                            )
                        else:
                            with new_zip.open(info.filename, mode='w') as new_file:
                                new_file.write(existing_zip.read(info))
                return new_zip_buffer.getvalue()
            else:
                # we don't need to add a guid, so just return fobj as normal
                fobj.seek(0)

        return fobj.read()


def call_signing(file_obj):
    """Sign `file_obj` via autographs /sign/file endpoint.

    :returns: the signed content (bytes)
    """
    conf = settings.AUTOGRAPH_CONFIG

    input_data = force_str(b64encode(add_guid(file_obj)))

    signing_data = {
        'input': input_data,
        'keyid': conf['signer'],
        'options': {
            'id': get_id(file_obj.version.addon),
            # Add-on variant A params (PKCS7 SHA256 and COSE ES256) work in
            # Fx >58 which is now the minimum version of Fx supported for signing.
            'pkcs7_digest': 'SHA256',
            'cose_algorithms': ['ES256'],
        },
    }

    hawk_auth = HawkAuth(id=conf['user_id'], key=conf['key'])

    # We are using a separate signer that adds the mozilla-recommendation.json
    # file.
    promo_group = file_obj.addon.promoted_group(currently_approved=False)
    if use_promoted_signer(file_obj, promo_group):
        signing_states = {
            promo_group.autograph_signing_states.get(app.short)
            for app in file_obj.addon.promotedaddon.all_applications
        }

        signing_data['keyid'] = conf['recommendation_signer']
        signing_data['options']['recommendations'] = list(signing_states)
        hawk_auth = HawkAuth(
            id=conf['recommendation_signer_user_id'],
            key=conf['recommendation_signer_key'],
        )

    with statsd.timer('services.sign.addon.autograph'):
        response = requests.post(
            '{server}/sign/file'.format(server=conf['server_url']),
            json=[signing_data],
            auth=hawk_auth,
        )

    if response.status_code != requests.codes.CREATED:
        msg = f'Posting to add-on signing failed ({response.status_code})'
        log.error(msg, extra={'reason': response.reason, 'text': response.text})
        raise SigningError(msg)

    return b64decode(response.json()[0]['signed_file'])


def sign_file(file_obj):
    """Sign a File if necessary.

    If it's not necessary (file exists but it's a mozilla signed one) then
    return the file directly.

    If there's no endpoint (signing is not enabled) or isn't reviewed yet,
    or there was an error while signing, raise an exception - it
    shouldn't happen.

    Otherwise proceed with signing and return the signed file.
    """
    from olympia.git.utils import create_git_extraction_entry

    if not settings.ENABLE_ADDON_SIGNING:
        raise SigningError(f'Not signing file {file_obj.pk}: no active endpoint')

    # No file? No signature.
    if not os.path.exists(file_obj.file.path):
        raise SigningError(f"File {file_obj.file.path} doesn't exist on disk")

    # Don't sign Mozilla signed extensions (they're already signed).
    if file_obj.is_mozilla_signed_extension:
        # Don't raise an exception here, just log and return file_obj even
        # though we didn't sign, it's not an error - we just don't need to do
        # anything in this case.
        log.info(
            'Not signing file {}: mozilla signed extension is already signed'.format(
                file_obj.pk
            )
        )
        return file_obj

    # We only sign files that are compatible with Firefox.
    if not supports_firefox(file_obj):
        raise SigningError(
            'Not signing version {}: not for a Firefox version we support'.format(
                file_obj.version.pk
            )
        )

    # Get the path before modifying it... We'll delete it after if signing was
    # successful and we ended up changing it.
    old_path = file_obj.file.path

    # Sign the file. If there's any exception, we skip the rest.
    signed_contents = call_signing(file_obj)

    # Prepare everything that needs to be saved. Note that the file isn't saved
    # to disk until the file_obj.save() call.
    # We need to pass _a_ name to ContentFile() so that the underlying code
    # to save the file works, but the name passed doesn't actually matter: it
    # will get overridden by the upload_to callback. Note that it means .name
    # and .path are not usable before the .save() call.
    signed_contents_as_file = ContentFile(signed_contents, name='addon.xpi')
    # Fetch the certificates serial number by extracting the file and
    # fetching the pkcs signature. Future versions of autograph may return this
    # in the response: https://github.com/mozilla-services/autograph/issues/214
    with zipfile.ZipFile(signed_contents_as_file) as zip_fobj:
        file_obj.cert_serial_num = get_signer_serial_number(
            zip_fobj.read(os.path.join('META-INF', 'mozilla.rsa'))
        )
    file_obj.is_signed = True
    file_obj.file = signed_contents_as_file
    file_obj.hash = file_obj.generate_hash()
    file_obj.size = file_obj.file.size
    # Django built-in methods seek(0) before reading, but let's add one just in
    # case something on our end tries a direct read() after.
    file_obj.file.seek(0)
    file_obj.save()
    log.info(f'Signing complete for file {file_obj.pk}')

    if waffle.switch_is_active('enable-uploads-commit-to-git-storage'):
        # Schedule this version for git extraction.
        transaction.on_commit(
            lambda: create_git_extraction_entry(version=file_obj.version)
        )

    # Remove old unsigned path if necessary.
    if old_path != file_obj.file.path:
        storage.delete(old_path)

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
    except (zipfile.BadZipFile, OSError):
        filenames = set()
    return {
        'META-INF/mozilla.rsa',
        'META-INF/mozilla.sf',
        'META-INF/manifest.mf',
    }.issubset(filenames)


class SignatureInfo:
    def __init__(self, pkcs7):
        if isinstance(pkcs7, SignatureInfo):
            # Allow passing around SignatureInfo objects to avoid
            # re-reading the signature every time.
            self.content = pkcs7.content
        else:
            self.content = cms.ContentInfo.load(pkcs7).native['content']

    @property
    def signer_serial_number(self):
        return self.signer_info['sid']['serial_number']

    @property
    def signer_info(self):
        """There should be only one SignerInfo for add-ons,
        nss doesn't support multiples

        See ttps://bugzilla.mozilla.org/show_bug.cgi?id=1357815#c4 for a few
        more details.
        """
        return self.content['signer_infos'][0]

    @property
    def issuer(self):
        return self.signer_info['sid']['issuer']

    @property
    def signer_certificate(self):
        for certificate in self.content['certificates']:
            info = certificate['tbs_certificate']
            is_signer_certificate = (
                info['issuer'] == self.issuer
                and info['serial_number'] == self.signer_serial_number
            )
            if is_signer_certificate:
                return info


def get_signer_serial_number(pkcs7):
    """Return the signer serial number of the signature."""
    return SignatureInfo(pkcs7).signer_serial_number


def get_signer_organizational_unit_name(pkcs7):
    """Return the OU of the signer certificate."""
    cert = SignatureInfo(pkcs7).signer_certificate
    return cert['subject']['organizational_unit_name']
