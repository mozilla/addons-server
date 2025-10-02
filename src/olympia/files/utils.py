import contextlib
import errno
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import signal
import stat
import struct
import tarfile
import tempfile
import zipfile
from types import MappingProxyType

from django import forms
from django.conf import settings
from django.core.files import File as DjangoFile
from django.core.files.storage import default_storage as storage
from django.template.defaultfilters import filesizeformat
from django.utils.encoding import force_str
from django.utils.jslex import JsLexer
from django.utils.translation import gettext

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.addons.utils import validate_addon_name
from olympia.amo.utils import decode_json, find_language, rm_local_tmp_dir
from olympia.applications.models import AppVersion
from olympia.lib import unicodehelper
from olympia.lib.crypto.signing import get_signer_organizational_unit_name
from olympia.versions.compare import VersionString


log = olympia.core.logger.getLogger('z.files.utils')


class ParseError(forms.ValidationError):
    pass


# Note: Long strings are a DOS risk, so always check the length of input to this regex.
VERSION_RE = re.compile(r'^[-+*.\w]*$', re.ASCII)
SIGNED_RE = re.compile(r'^META\-INF/(\w+)\.(rsa|sf)$')

# This is essentially what Firefox matches
# (see toolkit/components/extensions/ExtensionUtils.jsm)
MSG_RE = re.compile(r'__MSG_(?P<msgid>[a-zA-Z0-9@_]+?)__')


def get_filepath(fileorpath):
    """Resolve the actual file path of `fileorpath`.

    This supports various input formats, a path, a django `File` object,
    `olympia.files.File`, a `FileUpload` or just a regular file-like object.
    """
    from olympia.files.models import File, FileUpload

    if isinstance(fileorpath, str):
        return fileorpath
    elif isinstance(fileorpath, DjangoFile):
        return fileorpath
    elif isinstance(fileorpath, File):
        return fileorpath.file
    elif isinstance(fileorpath, FileUpload):
        return fileorpath.file_path
    elif hasattr(fileorpath, 'name'):  # file-like object
        return fileorpath.name
    return fileorpath


def get_file(fileorpath):
    """Get a file-like object, whether given a FileUpload, a (Django) File or
    a path."""
    if hasattr(fileorpath, 'file_path'):  # FileUpload
        if not fileorpath.path:
            # This upload has already been used to create a Version. Note that
            # we say "processed" but it's different than the `processed`
            # property on FileUpload, it's just used here as a generic term to
            # inform the developer this FileUpload has already been used.
            raise AlreadyUsedUpload(gettext('This upload has already been submitted.'))
        return storage.open(fileorpath.file_path, 'rb')
    elif hasattr(fileorpath, 'path'):
        return storage.open(fileorpath.path, 'rb')
    if hasattr(fileorpath, 'name'):
        return fileorpath
    return storage.open(fileorpath, 'rb')


def make_xpi(files):
    file_obj = io.BytesIO()
    zip_file = zipfile.ZipFile(file_obj, 'w')
    for path, data in files.items():
        zip_file.writestr(path, data)
    zip_file.close()
    file_obj.seek(0)
    return file_obj


class UnsupportedFileType(forms.ValidationError):
    pass


class NoManifestFound(forms.ValidationError):
    pass


class InvalidManifest(forms.ValidationError):
    pass


class InvalidArchiveFile(forms.ValidationError):
    """This error is raised when we attempt to open an invalid file with
    SafeZip/SafeTar."""

    pass


class AlreadyUsedUpload(forms.ValidationError):
    """Error raised when trying to use a FileUpload that has already been used
    to make a Version+File, its path will be empty."""

    pass


class DuplicateAddonID(forms.ValidationError):
    pass


# Return an immutable empty dict used as the fallback value when fetching
# manifest keys that are missing. Comparisons need to be done with the `is`
# operator to distinguish from an empty dict specified in the manifest.
EMPTY_FALLBACK_DICT = MappingProxyType({})


def get_simple_version(version_string):
    """Extract the version number without the ><= requirements, returning a
    VersionString instance.

    This simply extracts the version number without the ><= requirement so
    it will not be accurate for version requirements that are not >=, <= or
    = to a version.

    >>> get_simple_version('>=33.0a1')
    VersionString('33.0a1')
    """
    if not version_string:
        version_string = ''
    return VersionString(re.sub('[<=>]', '', version_string))


class ManifestJSONExtractor:
    """Extract add-on info from a manifest file."""

    def __init__(self, manifest_data, *, certinfo=None):
        self.certinfo = certinfo

        # Remove BOM if present.
        data = unicodehelper.decode(manifest_data)

        # Run through the JSON and remove all comments, then try to read
        # the manifest file.
        # Note that Firefox and the WebExtension spec only allow for
        # line comments (starting with `//`), not block comments (starting with
        # `/*`). We strip out both in AMO because the linter will flag the
        # block-level comments explicitly as an error (so the developer can
        # change them to line-level comments).
        #
        # But block level comments are not allowed. We just flag them elsewhere
        # (in the linter).
        json_string = ''
        lexer = JsLexer()
        for name, token in lexer.lex(data):
            if name not in ('blockcomment', 'linecomment'):
                json_string += token

        try:
            self.data = json.loads(json_string)
            if not isinstance(self.data, dict):
                raise TypeError()
        except Exception as exc:
            raise InvalidManifest(
                gettext('Could not parse the manifest file.')
            ) from exc

    def get(self, key, default=None):
        return self.data.get(key, default)

    @property
    def homepage(self):
        homepage_url = self.get('homepage_url')
        # `developer.url` in the manifest overrides `homepage_url`.
        return self.get('developer', EMPTY_FALLBACK_DICT).get('url', homepage_url)

    @property
    def is_experiment(self):
        """Return whether or not the webextension uses
        experiments or theme experiments API.

        In legacy extensions this is a different type, but for webextensions
        we just look at the manifest."""
        experiment_keys = ('experiment_apis', 'theme_experiment')
        return any(bool(self.get(key)) for key in experiment_keys)

    @property
    def gecko(self):
        """Return the "applications|browser_specific_settings["gecko"]" part
        of the manifest."""
        parent_block = self.get(
            'browser_specific_settings', self.get('applications', EMPTY_FALLBACK_DICT)
        )
        return parent_block.get('gecko', EMPTY_FALLBACK_DICT)

    @property
    def gecko_android(self):
        """Return `browser_specific_settings.gecko_android` if present."""
        return self.get('browser_specific_settings', EMPTY_FALLBACK_DICT).get(
            'gecko_android', EMPTY_FALLBACK_DICT
        )

    @property
    def guid(self):
        return str(self.gecko.get('id', None) or '') or None

    @property
    def type(self):
        return (
            amo.ADDON_LPAPP
            if 'langpack_id' in self.data
            else amo.ADDON_STATICTHEME
            if 'theme' in self.data
            else amo.ADDON_DICT
            if 'dictionaries' in self.data
            else amo.ADDON_EXTENSION
        )

    def get_strict_version_for(self, *, key, application):
        strict_key = f'strict_{key}_version'
        if application == amo.FIREFOX:
            strict_version_value = self.gecko.get(strict_key)
        elif application == amo.ANDROID:
            strict_version_value = self.gecko_android.get(
                strict_key, self.gecko.get(strict_key)
            )
        else:
            strict_version_value = None
        return get_simple_version(strict_version_value)

    @property
    def install_origins(self):
        value = self.get('install_origins', [])
        # We will be processing install_origins regardless of validation
        # status, so it can be invalid. We need to ensure it's a list of
        # strings at least, to prevent exceptions later.
        return (
            list(filter(lambda item: isinstance(item, str), value))
            if isinstance(value, list)
            else []
        )

    def apps(self):
        """Return `ApplicationsVersion`s (without the `version` field being
        set yet) for this manifest to be used in Version.from_upload()."""
        from olympia.versions.models import ApplicationsVersions

        type_ = self.type
        if type_ == amo.ADDON_LPAPP:
            # Langpack are only compatible with Firefox desktop at the moment.
            # https://github.com/mozilla/addons-server/issues/8381
            # They are all strictly compatible with a specific version, so
            # the default min version here doesn't matter much.
            apps = ((amo.FIREFOX, amo.DEFAULT_WEBEXT_MIN_VERSION),)
        elif type_ == amo.ADDON_STATICTHEME:
            # Static themes are only compatible with Firefox desktop >= 53.
            # They used to be compatible with Android, but that support was
            # removed.
            apps = ((amo.FIREFOX, amo.DEFAULT_STATIC_THEME_MIN_VERSION_FIREFOX),)
        elif type_ == amo.ADDON_DICT:
            # WebExt dicts are only compatible with Firefox desktop >= 61.
            apps = ((amo.FIREFOX, amo.DEFAULT_WEBEXT_DICT_MIN_VERSION_FIREFOX),)
        else:
            webext_min_firefox = amo.DEFAULT_WEBEXT_MIN_VERSION
            webext_min_android = (
                amo.DEFAULT_WEBEXT_MIN_VERSION_GECKO_ANDROID
                if self.gecko_android is not EMPTY_FALLBACK_DICT
                else amo.DEFAULT_WEBEXT_MIN_VERSION_ANDROID
            )
            apps = (
                (amo.FIREFOX, webext_min_firefox),
                (amo.ANDROID, webext_min_android),
            )

        if self.get('manifest_version') == 3:
            # Update minimum supported versions if it's an mv3 addon.
            mv3_mins = {
                amo.FIREFOX: amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_FIREFOX,
                amo.ANDROID: amo.DEFAULT_WEBEXT_MIN_VERSION_MV3_ANDROID,
            }
            apps = (
                (app, max(VersionString(ver), mv3_mins.get(app, mv3_mins[amo.FIREFOX])))
                for app, ver in apps
            )

        strict_min_version_firefox = self.get_strict_version_for(
            key='min', application=amo.FIREFOX
        )

        # If a minimum strict version is specified, it needs to be higher
        # than the version when Firefox started supporting WebExtensions.
        unsupported_no_matter_what = (
            strict_min_version_firefox
            and strict_min_version_firefox
            < VersionString(amo.DEFAULT_WEBEXT_MIN_VERSION)
        )
        if unsupported_no_matter_what:
            msg = gettext('Lowest supported "strict_min_version" is {min_version}.')
            raise forms.ValidationError(
                msg.format(min_version=amo.DEFAULT_WEBEXT_MIN_VERSION)
            )

        for app, default_min_version in apps:
            strict_min_version_from_manifest = self.get_strict_version_for(
                key='min', application=app
            )

            # strict_min_version for this app shouldn't be lower than the
            # default min version for this app.
            strict_min_version = max(
                strict_min_version_from_manifest, VersionString(default_min_version)
            )

            strict_max_version_from_manifest = self.get_strict_version_for(
                key='max', application=app
            )
            strict_max_version = strict_max_version_from_manifest or VersionString(
                amo.DEFAULT_WEBEXT_MAX_VERSION
            )

            if strict_max_version < strict_min_version:
                strict_max_version = strict_min_version

            qs = AppVersion.objects.filter(application=app.id)
            try:
                min_appver = qs.get(version=strict_min_version)
            except AppVersion.DoesNotExist as exc:
                msg = gettext(
                    'Unknown "strict_min_version" {appver} for {app}'.format(
                        app=app.pretty, appver=strict_min_version
                    )
                )
                raise forms.ValidationError(msg) from exc

            try:
                max_appver = qs.get(version=strict_max_version)
            except AppVersion.DoesNotExist as exc:
                # If the specified strict_max_version can't be found, raise an
                # error: we used to use '*' instead but this caused more
                # problems, especially with langpacks that are really specific
                # to a given Firefox version.
                msg = gettext(
                    'Unknown "strict_max_version" {appver} for {app}'.format(
                        app=app.pretty, appver=strict_max_version
                    )
                )
                raise forms.ValidationError(msg) from exc

            if app == amo.ANDROID and self.gecko_android is not EMPTY_FALLBACK_DICT:
                originated_from = amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST_GECKO_ANDROID
            elif strict_min_version_from_manifest or strict_max_version_from_manifest:
                # At least part of the compatibility came from the manifest.
                originated_from = amo.APPVERSIONS_ORIGINATED_FROM_MANIFEST
            else:
                originated_from = amo.APPVERSIONS_ORIGINATED_FROM_AUTOMATIC

            yield ApplicationsVersions(
                application=app.id,
                min=min_appver,
                max=max_appver,
                originated_from=originated_from,
            )

    def target_locale(self):
        """Guess target_locale for a dictionary/langpack from manifest contents."""
        try:
            if langpack_id := self.get('langpack_id'):
                return force_str(langpack_id)[:255]

            dictionaries = self.get('dictionaries', EMPTY_FALLBACK_DICT)
            key = force_str(list(dictionaries.keys())[0])
            return key[:255]
        except (IndexError, UnicodeDecodeError) as exc:
            # This shouldn't happen: the linter should prevent it, but
            # just in case, handle the error (without bothering with
            # translations as users should never see this).
            raise forms.ValidationError(
                'Invalid dictionaries object or langpack_id.'
            ) from exc

    def parse(self, minimal=False):
        data = {
            'guid': self.guid,
            'type': self.type,
            'version': str(self.get('version', '')),
            'name': self.get('name'),
            'summary': self.get('description'),
            'homepage': self.homepage,
            'default_locale': self.get('default_locale'),
            'manifest_version': self.get('manifest_version'),
            'install_origins': self.install_origins,
            'explicitly_compatible_with_android': (
                self.gecko_android is not EMPTY_FALLBACK_DICT
            ),
        }

        # Populate certificate information (e.g signed by mozilla or not)
        # early on to be able to verify compatibility based on it
        if self.certinfo is not None:
            data.update(self.certinfo.parse())

        if self.type == amo.ADDON_STATICTHEME:
            data['theme'] = self.get('theme', EMPTY_FALLBACK_DICT)

        if not minimal:
            data.update(
                {
                    'apps': list(self.apps()),
                    # Langpacks have strict compatibility enabled, rest of
                    # webextensions don't.
                    'strict_compatibility': data['type'] == amo.ADDON_LPAPP,
                    'is_experiment': self.is_experiment,
                }
            )
            if self.type == amo.ADDON_EXTENSION:
                # Only extensions have permissions and content scripts
                data.update(
                    {
                        'optional_permissions': self.get('optional_permissions', []),
                        'permissions': self.get('permissions', []),
                        'host_permissions': self.get('host_permissions', []),
                        'content_scripts': self.get('content_scripts', []),
                        'data_collection_permissions': self.gecko.get(
                            'data_collection_permissions', {}
                        ).get('required', []),
                        'optional_data_collection_permissions': self.gecko.get(
                            'data_collection_permissions', {}
                        ).get('optional', []),
                    }
                )

                if self.get('devtools_page'):
                    data.update({'devtools_page': self.get('devtools_page')})
            elif self.type in (amo.ADDON_DICT, amo.ADDON_LPAPP):
                data['target_locale'] = self.target_locale()
        return data


class SigningCertificateInformation:
    """Process the signature to determine the addon is a Mozilla Signed
    extension, so is signed already with a special certificate.  We want to
    know this so we don't write over it later, and stop unauthorised people
    from submitting them to AMO."""

    def __init__(self, certificate_data):
        pkcs7 = certificate_data
        self.cert_ou = get_signer_organizational_unit_name(pkcs7)

    @property
    def is_mozilla_signed_ou(self):
        return self.cert_ou == 'Mozilla Extensions'

    def parse(self):
        return {'is_mozilla_signed_extension': self.is_mozilla_signed_ou}


class FSyncMixin:
    """Mixin that implements fsync for file extractions.

    This mixin uses the `_extract_member` interface used by `ziplib` and
    `tarfile` so it's somewhat unversal.

    We need this to make sure that on EFS / NFS all data is immediately
    written to avoid any data loss on the way.
    """

    def _fsync_dir(self, path):
        descriptor = os.open(path, os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        except OSError as exc:
            # On some filesystem doing a fsync on a directory
            # raises an EINVAL error. Ignoring it is usually safe.
            if exc.errno != errno.EINVAL:
                raise
        os.close(descriptor)

    def _fsync_file(self, path):
        descriptor = os.open(path, os.O_RDONLY)
        os.fsync(descriptor)
        os.close(descriptor)

    def _extract_member(self, member, targetpath, *args, **kwargs):
        """Extends `ZipFile._extract_member` to call fsync().

        For every extracted file we are ensuring that it's data has been
        written to disk. We are doing this to avoid any data inconsistencies
        that we have seen in the past.

        To do this correctly we are fsync()ing all directories as well
        only that will ensure we have a durable write for that specific file.

        This is inspired by https://github.com/2ndquadrant-it/barman/
        (see backup.py -> backup_fsync_and_set_sizes and utils.py)
        """
        super()._extract_member(member, targetpath, *args, **kwargs)

        parent_dir = os.path.dirname(os.path.normpath(targetpath))
        if parent_dir:
            self._fsync_dir(parent_dir)

        self._fsync_file(targetpath)


class FSyncedZipFile(FSyncMixin, zipfile.ZipFile):
    """Subclass of ZipFile that calls `fsync` for file extractions."""

    pass


class FSyncedTarFile(FSyncMixin, tarfile.TarFile):
    """Subclass of TarFile that calls `fsync` for file extractions."""

    pass


def archive_member_validator(member, ignore_filename_errors=False):
    """Validate a member of an archive member (TarInfo or ZipInfo)."""
    filename = getattr(member, 'filename', getattr(member, 'name', None))
    filesize = getattr(member, 'file_size', getattr(member, 'size', None))
    compress_type = getattr(member, 'compress_type', None)

    if compress_type is not None and compress_type not in (
        zipfile.ZIP_STORED,
        zipfile.ZIP_DEFLATED,
    ):
        raise InvalidArchiveFile(gettext('Unsupported compression method in archive.'))

    if filename is None or filesize is None:
        raise InvalidArchiveFile(gettext('Unsupported archive type.'))

    try:
        force_str(filename)
    except UnicodeDecodeError as exc:
        # We can't log the filename unfortunately since it's encoding
        # is obviously broken :-/
        log.warning('Extraction error, invalid file name encoding')
        msg = gettext(
            'Invalid file name in archive. Please make sure '
            'all filenames are utf-8 or latin1 encoded.'
        )
        raise InvalidArchiveFile(msg) from exc

    if not ignore_filename_errors:
        if (
            '\\' in filename
            or '../' in filename
            or '..' == filename
            or filename.startswith('/')
        ):
            log.warning('Extraction error, invalid file name: %s', filename)
            # L10n: {0} is the name of the invalid file.
            msg = gettext('Invalid file name in archive: {0}')
            raise InvalidArchiveFile(msg.format(filename))

    if filesize > settings.FILE_UNZIP_SIZE_LIMIT:
        log.warning(
            'Extraction error, file too big for file (%s): %s', filename, filesize
        )
        # L10n: {0} is the name of the invalid file.
        msg = gettext('File exceeding size limit in archive: {0}')
        raise InvalidArchiveFile(msg.format(filename))


class SafeTar:
    @classmethod
    def open(cls, *args, **kwargs):
        if kwargs.pop('force_fsync', False):
            cls = FSyncedTarFile
        else:
            cls = tarfile.TarFile
        archive = cls.open(*args, **kwargs)
        for member in archive.getmembers():
            archive_member_validator(member)
            # In addition to the generic archive member validator, tar files
            # can contain special files we don't want...
            for method in ('isblk', 'ischr', 'isdev', 'isfifo', 'islnk', 'issym'):
                if getattr(member, method)():
                    raise InvalidArchiveFile(
                        gettext(
                            'This archive contains a forbidden special file '
                            '(symbolic / hard link or device / block file)'
                        )
                    )
        return archive


class SafeZip:
    def __init__(
        self, source, mode='r', force_fsync=False, ignore_filename_errors=False
    ):
        self.source = source
        self.info_list = None
        self.mode = mode
        self.force_fsync = force_fsync
        self.ignore_filename_errors = ignore_filename_errors
        self.initialize_and_validate()

    def initialize_and_validate(self):
        """
        Runs some overall archive checks.
        """
        if self.force_fsync:
            zip_file = FSyncedZipFile(self.source, self.mode)
        else:
            zip_file = zipfile.ZipFile(self.source, self.mode)

        info_list = zip_file.infolist()

        total_file_size = 0
        for info in info_list:
            total_file_size += info.file_size
            archive_member_validator(info, self.ignore_filename_errors)

        if total_file_size >= settings.MAX_ZIP_UNCOMPRESSED_SIZE:
            raise InvalidArchiveFile(gettext('Uncompressed size is too large'))

        self.info_list = info_list
        self.zip_file = zip_file

    def is_signed(self):
        """Tells us if an addon is signed."""
        finds = []
        for info in self.info_list:
            match = SIGNED_RE.match(info.filename)
            if match:
                name, ext = match.groups()
                # If it's rsa or sf, just look for the opposite.
                if (name, {'rsa': 'sf', 'sf': 'rsa'}[ext]) in finds:
                    return True
                finds.append((name, ext))

    def extract_info_to_dest(self, info, dest):
        """Extracts the given info to a directory and checks the file size."""
        self.zip_file.extract(info, dest)
        dest = os.path.join(dest, info.filename)

        if not os.path.isdir(dest):
            # Directories consistently report their size incorrectly.
            size = os.stat(dest)[stat.ST_SIZE]
            if size != info.file_size:
                log.warning(
                    'Extraction error, uncompressed size: %s, %s not %s',
                    self.source,
                    size,
                    info.file_size,
                )
                raise forms.ValidationError(gettext('Invalid archive.'))

    def extract_to_dest(self, dest):
        """Extracts the zip file to a directory."""
        for info in self.info_list:
            self.extract_info_to_dest(info, dest)

    def close(self):
        self.zip_file.close()

    @property
    def filelist(self):
        return self.zip_file.filelist

    @property
    def namelist(self):
        return self.zip_file.namelist

    def exists(self, path):
        try:
            return self.zip_file.getinfo(path)
        except KeyError:
            return False

    def read(self, path):
        return self.zip_file.read(path)


def extract_zip(source, remove=False, force_fsync=False, tempdir=None):
    """Extracts the zip file. If remove is given, removes the source file."""
    if tempdir is None:
        tempdir = tempfile.mkdtemp(dir=settings.TMP_PATH)

    try:
        zip_file = SafeZip(source, force_fsync=force_fsync)
        zip_file.extract_to_dest(tempdir)
    except Exception:
        rm_local_tmp_dir(tempdir)
        raise

    if remove:
        os.remove(source)
    return tempdir


def extract_extension_to_dest(source, dest=None, force_fsync=False):
    """Extract `source` to `dest`.

    `source` is the path to an extension or extension source, which can be a
    zip or a compressed tar (gzip, bzip)

    Note that this doesn't verify the contents of `source` except for
    that it requires something valid to be extracted.

    :returns: Extraction target directory, if `dest` is `None` it'll be a
              temporary directory.
    :raises FileNotFoundError: if the source file is not found on the filestem
    :raises forms.ValidationError: if the zip is invalid
    """
    target, tempdir = None, None

    if dest is None:
        target = tempdir = tempfile.mkdtemp(dir=settings.TMP_PATH)
    else:
        target = dest

    try:
        source = force_str(source)
        if source.endswith(('.zip', '.xpi')):
            with open(source, 'rb') as source_file:
                zip_file = SafeZip(source_file, force_fsync=force_fsync)
                zip_file.extract_to_dest(target)
        elif source.endswith(('.tar.gz', '.tar.bz2', '.tgz')):
            with SafeTar.open(source, force_fsync=force_fsync) as archive:
                archive.extractall(target)
        else:
            raise FileNotFoundError  # Unsupported file, shouldn't be reached
    except (
        zipfile.BadZipFile,
        tarfile.ReadError,
        OSError,
        forms.ValidationError,
    ) as exc:
        if tempdir is not None:
            rm_local_tmp_dir(tempdir)
        if isinstance(exc, (FileNotFoundError, forms.ValidationError)):
            # We let FileNotFoundError (which are a subclass of IOError, or
            # rather OSError but that's an alias) and ValidationError be
            # raised, the caller will have to deal with it.
            raise
        # Any other exceptions we caught, we raise a generic ValidationError
        # instead.
        raise forms.ValidationError(gettext('Invalid or broken archive.')) from exc
    return target


def copy_over(source, dest):
    """
    Copies from the source to the destination, removing the destination
    if it exists and is a directory.
    """
    if os.path.exists(dest) and os.path.isdir(dest):
        shutil.rmtree(dest)

    shutil.copytree(source, dest)
    # mkdtemp will set the directory permissions to 700
    # for the webserver to read them, we need 755
    os.chmod(
        dest, stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
    )
    shutil.rmtree(source)


def get_all_files(folder, strip_prefix='', prefix=None):
    """Return all files in a file/directory tree.

    :param folder: The folder of which to return the file-tree.
    :param strip_prefix str: A string to strip in case we're adding a custom
                             `prefix` Doesn't have any implications if
                             `prefix` isn't given.
    :param prefix: A custom prefix to add to all files and folders.
    """

    all_files = []

    # Not using os.path.walk so we get just the right order.
    def iterate(path):
        path_dirs, path_files = storage.listdir(path)
        for dirname in sorted(path_dirs):
            full = os.path.join(path, force_str(dirname))
            all_files.append(full)
            iterate(full)

        for filename in sorted(path_files):
            full = os.path.join(path, force_str(filename))
            all_files.append(full)

    iterate(folder)

    if prefix is not None:
        # This is magic: strip the prefix, e.g /tmp/ and prepend the prefix
        all_files = [
            os.path.join(prefix, fname[len(strip_prefix) + 1 :]) for fname in all_files
        ]

    return all_files


def extract_xpi(xpi, path):
    """Extract all files from `xpi` to `path`.

    This can be removed in favour of our already extracted git-repositories
    once we land and tested them in production.
    """
    tempdir = extract_zip(xpi)
    all_files = get_all_files(tempdir)

    copy_over(tempdir, path)
    return all_files


def parse_xpi(xpi, *, addon=None, minimal=False, user=None, bypass_name_checks=False):
    """Extract and parse an XPI. Returns a dict with various
    properties describing the xpi.

    Will raise ValidationError if something went wrong while parsing.

    If minimal is True, it avoids validation as much as possible (still raising
    ValidationError for hard errors like I/O or invalid json) and returns
    only the minimal set of properties needed to decide what to do with the
    add-on: guid and version.
    """
    try:
        xpi = get_file(xpi)
        zip_file = SafeZip(xpi)

        certificate = os.path.join('META-INF', 'mozilla.rsa')
        certificate_info = None

        if zip_file.exists(certificate):
            certificate_info = SigningCertificateInformation(zip_file.read(certificate))

        if zip_file.exists('manifest.json'):
            xpi_info = ManifestJSONExtractor(
                zip_file.read('manifest.json'), certinfo=certificate_info
            ).parse(minimal=minimal)
        else:
            raise NoManifestFound(gettext('No manifest.json found'))

    except forms.ValidationError:
        raise
    except zipfile.BadZipFile as exc:
        raise forms.ValidationError(gettext('Invalid or corrupted file.')) from exc
    except Exception as exc:
        # We don't really know what happened, so even though we return a
        # generic message about the manifest, don't raise InvalidManifest: it's
        # not just invalid, it's worse... We want the validation to stop there.
        log.exception(f'XPI parse error ({exc.__class__})')
        raise forms.ValidationError(
            gettext('Could not parse the manifest file.')
        ) from exc

    if minimal:
        return xpi_info
    return check_xpi_info(
        xpi_info,
        addon=addon,
        xpi_file=xpi,
        user=user,
        bypass_name_checks=bypass_name_checks,
    )


def check_xpi_info(
    xpi_info, *, addon=None, xpi_file=None, user=None, bypass_name_checks=False
):
    from olympia.addons.models import Addon, DeniedGuid
    from olympia.versions.models import Version

    guid = xpi_info['guid']

    # If we allow the guid to be omitted we assume that one was generated
    # or existed before and use that one.
    # An example are WebExtensions that don't require a guid but we generate
    # one once they're uploaded. Now, if you update that WebExtension we
    # just use the original guid.
    if addon and not guid:
        xpi_info['guid'] = guid = addon.guid

    if guid:
        if addon and addon.guid != guid:
            msg = gettext(
                'The add-on ID in your manifest.json (%s) '
                'does not match the ID of your add-on on AMO (%s)'
            )
            raise forms.ValidationError(msg % (guid, addon.guid))
        if not addon and (
            Addon.unfiltered.filter(guid=guid).exists()
            or DeniedGuid.objects.filter(guid=guid).exists()
        ):
            raise DuplicateAddonID(gettext('Duplicate add-on ID found.'))

    version_field_max_length = Version.version.field.max_length
    if len(xpi_info['version']) > version_field_max_length:
        raise forms.ValidationError(
            gettext(
                'Version numbers should have at most {max_length} characters.'
            ).format(max_length=version_field_max_length)
        )
    if not VERSION_RE.match(xpi_info['version']):
        raise forms.ValidationError(
            gettext(
                'Version numbers should only contain letters, numbers, '
                'and these punctuation characters: +*.-_.'
            )
        )

    if xpi_info.get('type') == amo.ADDON_STATICTHEME:
        max_size = settings.MAX_STATICTHEME_SIZE
        if xpi_file and xpi_file.size > max_size:
            raise forms.ValidationError(
                gettext('Maximum size for WebExtension themes is {0}.').format(
                    filesizeformat(max_size)
                )
            )

    if not bypass_name_checks and xpi_file:
        # Make sure we pass in a copy of `xpi_info` since
        # `resolve_webext_translations` modifies data in-place
        translations = Addon.resolve_webext_translations(xpi_info.copy(), xpi_file)
        validate_addon_name(translations['name'], user)

    # Parse the file to get and validate package data with the addon.
    if not acl.experiments_submission_allowed(user, xpi_info):
        raise forms.ValidationError(gettext('You cannot submit this type of add-on'))

    if not addon and not acl.reserved_guid_addon_submission_allowed(user, xpi_info):
        raise forms.ValidationError(
            gettext('You cannot submit an add-on using an ID ending with this suffix')
        )

    if not acl.mozilla_signed_extension_submission_allowed(user, xpi_info):
        raise forms.ValidationError(
            gettext('You cannot submit a Mozilla Signed Extension')
        )

    if not acl.langpack_submission_allowed(user, xpi_info):
        raise forms.ValidationError(gettext('You cannot submit a language pack'))

    if (
        addon
        and addon.target_locale
        and addon.target_locale != xpi_info['target_locale']
    ):
        raise forms.ValidationError(
            gettext(
                'The locale of an existing dictionary/language pack cannot be changed'
            )
        )

    return xpi_info


def parse_addon(pkg, *, addon=None, user=None, minimal=False, bypass_name_checks=False):
    """
    Extract and parse a file path, UploadedFile or FileUpload. Returns a dict
    with various properties describing the add-on.

    Will raise ValidationError if something went wrong while parsing.

    `addon` parameter is mandatory if the file being parsed is going to be
    attached to an existing Addon instance.

    `user` parameter is mandatory unless minimal `parameter` is True. It should
    point to the UserProfile responsible for the upload.

    If `minimal` parameter is True, it avoids validation as much as possible
    (still raising ValidationError for hard errors like I/O or invalid
    json) and returns only the minimal set of properties needed to decide
    what to do with the add-on (the exact set depends on the add-on type, but
    it should always contain at least guid, type and version.

    If `bypass_name_checks` is False, name checks are bypassed. It
    can be useful when parsing existing add-ons that may have been created
    before trademark validation rules went into effect.
    """
    name = getattr(pkg, 'name', pkg)
    if name.endswith(amo.VALID_ADDON_FILE_EXTENSIONS):
        parsed = parse_xpi(
            pkg,
            addon=addon,
            minimal=minimal,
            user=user,
            bypass_name_checks=bypass_name_checks,
        )
    else:
        valid_extensions_string = '(%s)' % ', '.join(amo.VALID_ADDON_FILE_EXTENSIONS)
        raise UnsupportedFileType(
            gettext(
                'Unsupported file type, please upload a supported '
                'file {extensions}.'.format(extensions=valid_extensions_string)
            )
        )

    if not minimal:
        if user is None:
            # This should never happen and means there is a bug in
            # addons-server itself.
            raise forms.ValidationError(gettext('Unexpected error.'))

        # FIXME: do the checks depending on user here.
        if addon and addon.type != parsed['type']:
            msg = gettext(
                'The type (%s) does not match the type of your add-on on AMO (%s)'
            )
            raise forms.ValidationError(
                msg
                % (
                    amo.ADDON_TYPE.get(parsed['type'], gettext('Unknown')),
                    addon.get_type_display(),
                )
            )
    return parsed


def get_sha256(file_obj):
    """Calculate a sha256 hash for `file_obj`.

    `file_obj` must either be be an open file descriptor, in which case the
    caller needs to take care of closing it properly, or a django File-like
    object with a chunks() method to iterate over its contents."""
    hash_ = hashlib.sha256()
    if hasattr(file_obj, 'chunks') and callable(file_obj.chunks):
        iterator = file_obj.chunks()
    else:
        iterator = iter(lambda: file_obj.read(io.DEFAULT_BUFFER_SIZE), b'')
    for chunk in iterator:
        hash_.update(chunk)
    return hash_.hexdigest()


class InvalidOrUnsupportedCrx(Exception):
    pass


def write_crx_as_xpi(chunks, target):
    """Extract and strip the header from the CRX, convert it to a regular ZIP
    archive, then write it to `target`, returning the sha256 hash hex digest.

    Read more about the CRX file format:
    https://developer.chrome.com/extensions/crx
    """
    # First we open the uploaded CRX so we can see how much we need
    # to trim from the header of the file to make it a valid ZIP.
    with tempfile.NamedTemporaryFile('w+b', dir=settings.TMP_PATH) as tmp:
        for chunk in chunks:
            tmp.write(chunk)

        tmp.seek(0)

        # Where we have to start to find the zip depends on the version of the
        # crx format. First let's confirm it's a crx by looking at the first
        # 4 bytes (32 bits)
        if tmp.read(4) != b'Cr24':
            raise InvalidOrUnsupportedCrx('CRX file does not start with Cr24')

        try:
            # Then read the version, which is in the next 4 bytes
            version = struct.unpack('<I', tmp.read(4))[0]

            # Then find out where we need to start from to find the zip inside.
            if version == 2:
                header_info = struct.unpack('<II', tmp.read(8))
                public_key_length = header_info[0]
                signature_length = header_info[1]
                # Start position is where we are so far (4 + 4 + 8 = 16) + the
                # two length values we extracted.
                start_position = 16 + public_key_length + signature_length
            elif version == 3:
                # Start position is where we are so far (4 + 4 + 4 = 12) + the
                # single header length value we extracted.
                header_length = struct.unpack('<I', tmp.read(4))[0]
                start_position = 12 + header_length
            else:
                raise InvalidOrUnsupportedCrx('Unsupported CRX version')
        except struct.error as exc:
            raise InvalidOrUnsupportedCrx('Invalid or corrupt CRX file') from exc

        # We can start reading the zip to write it where it needs to live on
        # the filesystem and then return the hash to the caller. If we somehow
        # don't end up with a valid xpi file, validation will raise an error
        # later.
        tmp.seek(start_position)
        hash_value = hashlib.sha256()
        # Now we open the Django storage and write our real XPI file.
        with storage.open(target, 'wb') as file_destination:
            data = tmp.read(65536)
            # Keep reading bytes and writing them to the XPI.
            while data:
                hash_value.update(data)
                file_destination.write(data)
                data = tmp.read(65536)

    return hash_value


def extract_translations(file_obj):
    """Extract all translation messages from `file_obj`."""
    xpi = get_filepath(file_obj)

    messages = {}

    try:
        with zipfile.ZipFile(xpi, 'r') as source:
            file_list = source.namelist()

            # Fetch all locales the add-on supports
            # see https://developer.chrome.com/extensions/i18n#overview-locales
            # for more details on the format.
            locales = {
                name.split('/')[1]
                for name in file_list
                if name.startswith('_locales/') and name.endswith('/messages.json')
            }

            for locale in locales:
                corrected_locale = find_language(locale)

                # Filter out languages we don't support.
                if not corrected_locale:
                    continue

                fname = f'_locales/{locale}/messages.json'

                try:
                    data = source.read(fname)
                    messages[corrected_locale] = decode_json(data)
                except (ValueError, KeyError):
                    # `ValueError` thrown by `decode_json` if the json is
                    # invalid and `KeyError` thrown by `source.read`
                    # usually means the file doesn't exist for some reason,
                    # we fail silently
                    continue
    except OSError:
        pass

    return messages


def resolve_i18n_message(message, messages, locale, default_locale=None):
    """Resolve a translatable string in an add-on.

    This matches ``__MSG_extensionName__`` like names and returns the correct
    translation for `locale`.

    :param locale: The locale to fetch the translation for, If ``None``
                   (default) ``settings.LANGUAGE_CODE`` is used.
    :param messages: A dictionary of messages, e.g the return value
                     of `extract_translations`.
    """
    if not message or not isinstance(message, str):
        # Don't even attempt to extract invalid data.
        # See https://github.com/mozilla/addons-server/issues/3067
        # for more details
        return message

    match = MSG_RE.match(message)

    if match is None:
        return message

    locale = find_language(locale)

    if default_locale:
        default_locale = find_language(default_locale)

    msgid = match.group('msgid')
    default = {'message': message} if default_locale else {'message': None}

    if locale in messages:
        message = messages[locale].get(msgid, default)
    elif default_locale in messages:
        message = messages[default_locale].get(msgid, default)

    if not isinstance(message, dict):
        # Fallback for invalid message format, should be caught by
        # addons-linter in the future but we'll have to handle it.
        # See https://github.com/mozilla/addons-server/issues/3485
        return default['message']

    resolved_message = message['message']
    # Check if the message has placeholders
    try:
        if 'placeholders' in message and isinstance(message['placeholders'], dict):
            for placeholder, content in message['placeholders'].items():
                if 'content' in content:
                    # Replace the placeholder with its content
                    resolved_message = re.sub(
                        f'\\${placeholder}\\$',
                        content['content'],
                        resolved_message,
                        flags=re.IGNORECASE,
                    )
    except (AttributeError, KeyError):
        pass

    return resolved_message


def get_background_images(file_obj, theme_data, header_only=False):
    """Extract static theme header image from `file_obj` and return in dict."""
    xpi = get_filepath(file_obj)
    if not theme_data:
        # we might already have theme_data, but otherwise get it from the xpi.
        try:
            parsed_data = parse_xpi(xpi, minimal=True)
            theme_data = parsed_data.get('theme', EMPTY_FALLBACK_DICT)
        except forms.ValidationError:
            # If we can't parse the existing manifest safely return.
            return {}
    images_dict = theme_data.get('images', EMPTY_FALLBACK_DICT)
    # Get the reference in the manifest.  headerURL is the deprecated variant.
    header_url = images_dict.get('theme_frame', images_dict.get('headerURL'))
    # And any additional backgrounds too.
    additional_urls = (
        images_dict.get('additional_backgrounds', []) if not header_only else []
    )
    image_urls = [header_url] + additional_urls
    images = {}
    try:
        with zipfile.ZipFile(xpi, 'r') as source:
            for url in image_urls:
                _, file_ext = os.path.splitext(str(url).lower())
                if file_ext not in amo.THEME_BACKGROUND_EXTS:
                    # Just extract image files.
                    continue
                try:
                    images[url] = source.read(url)
                except KeyError:
                    pass
    except OSError as ioerror:
        log.info(ioerror)
    return images


@contextlib.contextmanager
def run_with_timeout(seconds):
    """Implement timeouts via `signal`.

    This is being used to implement timeout handling when acquiring locks.
    """

    def timeout_handler(signum, frame):
        """
        Since Python 3.5 `fcntl` is retried automatically when interrupted.

        We need an exception to stop it. This exception will propagate on
        to the main thread, make sure `flock` is called there.
        """
        raise TimeoutError

    original_handler = signal.signal(signal.SIGALRM, timeout_handler)

    try:
        signal.alarm(seconds)
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, original_handler)


@contextlib.contextmanager
def lock(lock_dir, lock_name, timeout=6):
    """A wrapper around fcntl to be used as a context manager.

    Additionally this helper allows the caller to wait for a lock for a certain
    amount of time.

    Example::

        with lock(settings.TMP_PATH, 'extraction-1234'):
            extract_xpi(...)


    The lock is properly released at the end of the context block.

    This locking mechanism should work perfectly fine with NFS v4 and EFS
    (which uses the NFS v4.1 protocol).

    :param timeout: Timeout for how long we expect to wait for a lock in
                    seconds. If 0 the function returns immediately, otherwise
                    it blocks the execution.
    :return: `True` if the lock was attained, we are owning the lock,
             `False` if there is an already existing lock.
    """
    lock_name = f'{lock_name}.lock'

    log.info(f'Acquiring lock {lock_name}.')

    lock_path = os.path.join(lock_dir, lock_name)

    with open(lock_path, 'w') as lockfd:
        lockfd.write(f'{os.getpid()}')
        fileno = lockfd.fileno()

        try:
            with run_with_timeout(timeout):
                fcntl.flock(fileno, fcntl.LOCK_EX)
        except (BlockingIOError, TimeoutError):
            # Another process already holds the lock.
            # In theory, in this case we'd always catch
            # `TimeoutError` but for the sake of completness let's
            # catch `BlockingIOError` too to be on the safe side.
            yield False
        else:
            # We successfully acquired the lock.
            yield True
        finally:
            # Always release the lock after the parent context
            # block has finised.
            log.info(f'Releasing lock {lock_name}.')
            fcntl.flock(fileno, fcntl.LOCK_UN)
            lockfd.close()

            try:
                os.unlink(lock_path)
            except FileNotFoundError:
                pass
