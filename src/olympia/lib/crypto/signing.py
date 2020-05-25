import hashlib
import os
import zipfile

from base64 import b64decode, b64encode

from django.db import transaction
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.core.exceptions import ObjectDoesNotExist
from django.utils.encoding import force_bytes, force_text

import requests
import waffle

from django_statsd.clients import statsd
from requests_hawk import HawkAuth
from asn1crypto import cms

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
    return force_text(hashlib.sha256(guid).hexdigest())


def use_recommendation_signer(file_obj):
    try:
        return (
            file_obj.version.channel == amo.RELEASE_CHANNEL_LISTED and
            file_obj.version.addon.discoveryitem.recommendable)
    except ObjectDoesNotExist:
        pass

    return False


def call_signing(file_obj):
    """Sign `file_obj` via autographs /sign/file endpoint.

    :returns: The certificates serial number.
    """
    conf = settings.AUTOGRAPH_CONFIG

    with storage.open(file_obj.current_file_path) as fobj:
        input_data = force_text(b64encode(fobj.read()))

    signing_data = {
        'input': input_data,
        'keyid': conf['signer'],
        'options': {
            'id': get_id(file_obj.version.addon),
            # "Add-on variant A params (PKCS7 SHA1 and COSE ES256) work in
            # Fx <57, so we can switch to that without breaking backwards
            # compatibility"
            # https://github.com/mozilla/addons-server/issues/9308
            # This means, the pkcs7 sha1 signature is used for backwards
            # compatibility and cose sha256 will be used for newer
            # Firefox versions.
            # The relevant pref in Firefox is
            # "security.signed_app_signatures.policy"
            # where it's set to COSEAndPKCS7WithSHA1OrSHA256 to match
            # these settings.
            'pkcs7_digest': 'SHA1',
            'cose_algorithms': ['ES256']
        },
    }

    hawk_auth = HawkAuth(id=conf['user_id'], key=conf['key'])

    # We are using a separate signer that adds the mozilla-recommendation.json
    # file. There is currently only `recommended` as a type but more may be
    # added later, e.g partner.
    if use_recommendation_signer(file_obj):
        signing_data['keyid'] = conf['recommendation_signer']
        signing_data['options']['recommendations'] = ['recommended']
        hawk_auth = HawkAuth(
            id=conf['recommendation_signer_user_id'],
            key=conf['recommendation_signer_key'])

    with statsd.timer('services.sign.addon.autograph'):
        response = requests.post(
            '{server}/sign/file'.format(server=conf['server_url']),
            json=[signing_data],
            auth=hawk_auth)

    if response.status_code != requests.codes.CREATED:
        msg = u'Posting to add-on signing failed: {0} {1}'.format(
            response.reason, response.text)
        log.error(msg)
        raise SigningError(msg)

    # Save the returned file in our storage.
    with storage.open(file_obj.current_file_path, 'wb') as fobj:
        fobj.write(b64decode(response.json()[0]['signed_file']))

    # Now fetch the certificates serial number. Future versions of
    # autograph may return this in the response.
    # https://github.com/mozilla-services/autograph/issues/214
    # Now extract the file and fetch the pkcs signature
    with zipfile.ZipFile(file_obj.current_file_path, mode='r') as zip_fobj:
        return get_signer_serial_number(zip_fobj.read(
            os.path.join('META-INF', 'mozilla.rsa')))


def sign_file(file_obj):
    """Sign a File if necessary.

    If it's not necessary (file exists but it's a mozilla signed one, or it's
    a search plugin) then return the file directly.

    If there's no endpoint (signing is not enabled) or isn't reviewed yet,
    or there was an error while signing, raise an exception - it
    shouldn't happen.

    Otherwise proceed with signing and return the signed file.
    """
    from olympia.git.utils import create_git_extraction_entry

    if (file_obj.version.addon.type == amo.ADDON_SEARCH and
            file_obj.version.is_webextension is False):
        # Those aren't meant to be signed, we shouldn't be here.
        return file_obj

    if not settings.ENABLE_ADDON_SIGNING:
        raise SigningError(u'Not signing file {0}: no active endpoint'.format(
            file_obj.pk))

    # No file? No signature.
    if not os.path.exists(file_obj.current_file_path):
        raise SigningError(u'File {0} doesn\'t exist on disk'.format(
            file_obj.current_file_path))

    # Don't sign Mozilla signed extensions (they're already signed).
    if file_obj.is_mozilla_signed_extension:
        # Don't raise an exception here, just log and return file_obj even
        # though we didn't sign, it's not an error - we just don't need to do
        # anything in this case.
        log.info(u'Not signing file {0}: mozilla signed extension is already '
                 u'signed'.format(file_obj.pk))
        return file_obj

    # We only sign files that are compatible with Firefox.
    if not supports_firefox(file_obj):
        raise SigningError(
            u'Not signing version {0}: not for a Firefox version we support'
            .format(file_obj.version.pk))

    # Sign the file. If there's any exception, we skip the rest.
    cert_serial_num = str(call_signing(file_obj))

    size = storage.size(file_obj.current_file_path)

    # Save the certificate serial number for revocation if needed, and re-hash
    # the file now that it's been signed.
    file_obj.update(cert_serial_num=cert_serial_num,
                    hash=file_obj.generate_hash(),
                    is_signed=True,
                    size=size)
    log.info(u'Signing complete for file {0}'.format(file_obj.pk))

    if waffle.switch_is_active('enable-uploads-commit-to-git-storage'):
        # Schedule this version for git extraction.
        transaction.on_commit(
            lambda: create_git_extraction_entry(version=file_obj.version)
        )

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


class SignatureInfo(object):

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
                info['issuer'] == self.issuer and
                info['serial_number'] == self.signer_serial_number
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
