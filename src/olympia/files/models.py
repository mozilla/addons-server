import hashlib
import json
import os
import posixpath
import re
import unicodedata
import uuid

from urllib.parse import urljoin

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import models
from django.dispatch import receiver
from django.template.defaultfilters import slugify
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes, force_text
from django.utils.functional import cached_property

from django_extensions.db.fields.json import JSONField
from django_statsd.clients import statsd

import olympia.core.logger

from olympia import amo
from olympia.amo.decorators import use_primary_db
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import ManagerBase, ModelBase, OnChangeMixin
from olympia.amo.storage_utils import copy_stored_file, move_stored_file
from olympia.amo.templatetags.jinja_helpers import (
    urlparams, user_media_path, user_media_url)
from olympia.amo.urlresolvers import reverse
from olympia.applications.models import AppVersion
from olympia.files.utils import get_sha256, write_crx_as_xpi


log = olympia.core.logger.getLogger('z.files')


class File(OnChangeMixin, ModelBase):
    id = PositiveAutoField(primary_key=True)
    STATUS_CHOICES = amo.STATUS_CHOICES_FILE

    version = models.ForeignKey(
        'versions.Version', related_name='files',
        on_delete=models.CASCADE)
    platform = models.PositiveIntegerField(
        choices=amo.SUPPORTED_PLATFORMS_CHOICES,
        default=amo.PLATFORM_ALL.id,
        db_column='platform_id'
    )
    filename = models.CharField(max_length=255, default='')
    size = models.PositiveIntegerField(default=0)  # In bytes.
    hash = models.CharField(max_length=255, default='')
    # The original hash of the file, before we sign it, or repackage it in
    # any other way.
    original_hash = models.CharField(max_length=255, default='')
    status = models.PositiveSmallIntegerField(
        choices=STATUS_CHOICES.items(), default=amo.STATUS_AWAITING_REVIEW)
    datestatuschanged = models.DateTimeField(null=True, auto_now_add=True)
    is_restart_required = models.BooleanField(default=False)
    strict_compatibility = models.BooleanField(default=False)
    reviewed = models.DateTimeField(null=True, blank=True)
    # The `binary` field is used to store the flags from amo-validator when it
    # finds files with binary extensions or files that may contain binary
    # content.
    binary = models.BooleanField(default=False)
    # The `binary_components` field is used to store the flag from
    # amo-validator when it finds "binary-components" in the chrome manifest
    # file, used for default to compatible.
    binary_components = models.BooleanField(default=False)
    # Serial number of the certificate use for the signature.
    cert_serial_num = models.TextField(blank=True)
    # Is the file signed by Mozilla?
    is_signed = models.BooleanField(default=False)
    # Is the file an experiment (see bug 1220097)?
    is_experiment = models.BooleanField(default=False)
    # Is the file a WebExtension?
    is_webextension = models.BooleanField(default=False)
    # Is the file a special "Mozilla Signed Extension"
    # see https://wiki.mozilla.org/Add-ons/InternalSigning
    is_mozilla_signed_extension = models.BooleanField(default=False)
    # The user has disabled this file and this was its status.
    # STATUS_NULL means the user didn't disable the File - i.e. Mozilla did.
    original_status = models.PositiveSmallIntegerField(
        default=amo.STATUS_NULL)

    class Meta(ModelBase.Meta):
        db_table = 'files'
        indexes = [
            models.Index(fields=('created', 'version'),
                         name='created_idx'),
            models.Index(fields=('binary_components',), name='files_cedd2560'),
            models.Index(fields=('datestatuschanged', 'version'),
                         name='statuschanged_idx'),
            models.Index(fields=('platform',), name='platform_id'),
            models.Index(fields=('status',), name='status'),
        ]

    def __str__(self):
        return str(self.id)

    def get_platform_display(self):
        return force_text(amo.PLATFORMS[self.platform].name)

    @property
    def has_been_validated(self):
        try:
            self.validation
        except FileValidation.DoesNotExist:
            return False
        else:
            return True

    @property
    def automated_signing(self):
        """True if this file is eligible for automated signing. This currently
        means that either its version is unlisted."""
        return self.version.channel == amo.RELEASE_CHANNEL_UNLISTED

    def get_file_cdn_url(self, attachment=False):
        """Return the URL for the file corresponding to this instance
        on the CDN."""
        if attachment:
            host = posixpath.join(user_media_url('addons'), '_attachments')
        else:
            host = user_media_url('addons')

        return posixpath.join(
            *map(force_bytes, [host, self.version.addon.id, self.filename]))

    def get_url_path(self, src, attachment=False):
        return self._make_download_url(
            'downloads.file', src, attachment=attachment)

    def _make_download_url(self, view_name, src, attachment=False):
        kwargs = {
            'file_id': self.pk
        }
        if attachment:
            kwargs['type'] = 'attachment'
        url = os.path.join(reverse(view_name, kwargs=kwargs), self.filename)
        return urlparams(url, src=src)

    @classmethod
    def from_upload(cls, upload, version, platform, parsed_data=None):
        """
        Create a File instance from a FileUpload, a Version, a platform id
        and the parsed_data generated by parse_addon().

        Note that it's the caller's responsability to ensure the file is valid.
        We can't check for that here because an admin may have overridden the
        validation results."""
        assert parsed_data is not None

        file_ = cls(version=version, platform=platform)
        upload_path = force_text(nfd_str(upload.path))
        ext = force_text(os.path.splitext(upload_path)[1])
        file_.filename = file_.generate_filename(extension=ext or '.xpi')
        # Size in bytes.
        file_.size = storage.size(upload_path)
        file_.is_restart_required = parsed_data.get(
            'is_restart_required', False)
        file_.strict_compatibility = parsed_data.get(
            'strict_compatibility', False)
        file_.is_experiment = parsed_data.get('is_experiment', False)
        file_.is_webextension = parsed_data.get('is_webextension', False)
        file_.is_mozilla_signed_extension = parsed_data.get(
            'is_mozilla_signed_extension', False)

        file_.hash = file_.generate_hash(upload_path)
        file_.original_hash = file_.hash
        file_.save()

        if file_.is_webextension:
            permissions = list(parsed_data.get('permissions', []))
            # Add content_scripts host matches too.
            for script in parsed_data.get('content_scripts', []):
                permissions.extend(script.get('matches', []))
            if permissions:
                WebextPermission.objects.create(permissions=permissions,
                                                file=file_)

        log.debug('New file: %r from %r' % (file_, upload))

        # Move the uploaded file from the temp location.
        copy_stored_file(upload_path, file_.current_file_path)

        if upload.validation:
            validation = json.loads(upload.validation)
            FileValidation.from_json(file_, validation)

        return file_

    def generate_hash(self, filename=None):
        """Generate a hash for a file."""
        with open(filename or self.current_file_path, 'rb') as fobj:
            return 'sha256:{}'.format(get_sha256(fobj))

    def generate_filename(self, extension=None):
        """
        Files are in the format of:
        {addon_name}-{version}-{apps}-{platform}
        """
        parts = []
        addon = self.version.addon
        # slugify drops unicode so we may end up with an empty string.
        # Apache did not like serving unicode filenames (bug 626587).
        extension = extension or '.xpi'
        name = slugify(addon.name).replace('-', '_') or 'addon'
        parts.append(name)
        parts.append(self.version.version)

        if addon.type not in amo.NO_COMPAT and self.version.compatible_apps:
            apps = '+'.join(sorted([a.shortername for a in
                                    self.version.compatible_apps]))
            parts.append(apps)

        if self.platform and self.platform != amo.PLATFORM_ALL.id:
            parts.append(amo.PLATFORMS[self.platform].shortname)

        self.filename = '-'.join(parts) + extension
        return self.filename

    _pretty_filename = re.compile(r'(?P<slug>[a-z0-7_]+)(?P<suffix>.*)')

    def pretty_filename(self, maxlen=20):
        """Displayable filename.

        Truncates filename so that the slug part fits maxlen.
        """
        m = self._pretty_filename.match(self.filename)
        if not m:
            return self.filename
        if len(m.group('slug')) < maxlen:
            return self.filename
        return u'%s...%s' % (m.group('slug')[0:(maxlen - 3)],
                             m.group('suffix'))

    def latest_xpi_url(self, attachment=False):
        addon = self.version.addon
        kw = {'addon_id': addon.slug}
        if self.platform != amo.PLATFORM_ALL.id:
            kw['platform'] = self.platform
        if attachment:
            kw['type'] = 'attachment'
        return os.path.join(reverse('downloads.latest', kwargs=kw),
                            'addon-%s-latest%s' % (addon.pk, self.extension))

    @property
    def file_path(self):
        return os.path.join(user_media_path('addons'),
                            str(self.version.addon_id),
                            self.filename)

    @property
    def addon(self):
        return self.version.addon

    @property
    def guarded_file_path(self):
        return os.path.join(user_media_path('guarded_addons'),
                            str(self.version.addon_id), self.filename)

    @property
    def current_file_path(self):
        """Returns the current path of the file, whether or not it is
        guarded."""

        file_disabled = self.status == amo.STATUS_DISABLED
        addon_disabled = self.addon.is_disabled
        if file_disabled or addon_disabled:
            return self.guarded_file_path
        else:
            return self.file_path

    @property
    def fallback_file_path(self):
        """Fallback path in case the file was disabled/re-enabled and not yet
        moved - sort of the opposite to current_file_path. This should only be
        used for things like code search or git extraction where we really want
        the file contents no matter what."""
        return (
            self.file_path if self.current_file_path == self.guarded_file_path
            else self.guarded_file_path
        )

    @property
    def extension(self):
        return os.path.splitext(self.filename)[-1]

    def move_file(self, source_path, destination_path, log_message):
        """Move a file from `source_path` to `destination_path` and delete the
        source directory if it's empty once the file has been successfully
        moved.

        Meant to move files from/to the guarded file path as they are disabled
        or re-enabled.

        IOError and UnicodeEncodeError are caught and logged."""
        log_message = force_text(log_message)
        try:
            if storage.exists(source_path):
                source_parent_path = os.path.dirname(source_path)
                log.info(log_message.format(
                    source=source_path, destination=destination_path))
                move_stored_file(source_path, destination_path)
                # Now that the file has been deleted, remove the directory if
                # it exists to prevent the main directory from growing too
                # much (#11464)
                remaining_dirs, remaining_files = storage.listdir(
                    source_parent_path)
                if len(remaining_dirs) == len(remaining_files) == 0:
                    storage.delete(source_parent_path)
        except (UnicodeEncodeError, IOError):
            msg = u'Move Failure: {} {}'.format(source_path, destination_path)
            log.exception(msg)

    def hide_disabled_file(self):
        """Move a file from the public path to the guarded file path."""
        if not self.filename:
            return
        src, dst = self.file_path, self.guarded_file_path
        self.move_file(
            src, dst, 'Moving disabled file: {source} => {destination}')

    def unhide_disabled_file(self):
        """Move a file from guarded file path to the public file path."""
        if not self.filename:
            return
        src, dst = self.guarded_file_path, self.file_path
        self.move_file(
            src, dst, 'Moving undisabled file: {source} => {destination}')

    @cached_property
    def webext_permissions_list(self):
        if not self.is_webextension:
            return []
        try:
            # Filter out any errant non-strings included in the manifest JSON.
            # Remove any duplicate permissions.
            permissions = set()
            permissions = [p for p in self._webext_permissions.permissions
                           if isinstance(p, str) and not
                           (p in permissions or permissions.add(p))]
            return permissions

        except WebextPermission.DoesNotExist:
            return []


@use_primary_db
def update_status(sender, instance, **kw):
    if not kw.get('raw'):
        try:
            addon = instance.version.addon
            if 'delete' in kw:
                addon.update_status(ignore_version=instance.version)
            else:
                addon.update_status()
        except models.ObjectDoesNotExist:
            pass


def update_status_delete(sender, instance, **kw):
    kw['delete'] = True
    return update_status(sender, instance, **kw)


models.signals.post_save.connect(
    update_status, sender=File, dispatch_uid='version_update_status')
models.signals.post_delete.connect(
    update_status_delete, sender=File, dispatch_uid='version_update_status')


@receiver(models.signals.post_delete, sender=File,
          dispatch_uid='cleanup_file')
def cleanup_file(sender, instance, **kw):
    """ On delete of the file object from the database, unlink the file from
    the file system """
    if kw.get('raw') or not instance.filename:
        return
    # Use getattr so the paths are accessed inside the try block.
    for path in ('file_path', 'guarded_file_path'):
        try:
            filename = getattr(instance, path)
        except models.ObjectDoesNotExist:
            return
        if storage.exists(filename):
            log.info('Removing filename: %s for file: %s'
                     % (filename, instance.pk))
            storage.delete(filename)


@File.on_change
def check_file(old_attr, new_attr, instance, sender, **kw):
    if kw.get('raw'):
        return
    old, new = old_attr.get('status'), instance.status
    if new == amo.STATUS_DISABLED and old != amo.STATUS_DISABLED:
        instance.hide_disabled_file()
    elif old == amo.STATUS_DISABLED and new != amo.STATUS_DISABLED:
        instance.unhide_disabled_file()

    # Log that the hash has changed.
    old, new = old_attr.get('hash'), instance.hash
    if old != new:
        try:
            addon = instance.version.addon.pk
        except models.ObjectDoesNotExist:
            addon = 'unknown'
        log.info('Hash changed for file: %s, addon: %s, from: %s to: %s' %
                 (instance.pk, addon, old, new))


def track_new_status(sender, instance, *args, **kw):
    if kw.get('raw'):
        # The file is being loaded from a fixure.
        return
    if kw.get('created'):
        track_file_status_change(instance)


models.signals.post_save.connect(track_new_status,
                                 sender=File,
                                 dispatch_uid='track_new_file_status')


@File.on_change
def track_status_change(old_attr=None, new_attr=None, **kwargs):
    if old_attr is None:
        old_attr = {}
    if new_attr is None:
        new_attr = {}
    new_status = new_attr.get('status')
    old_status = old_attr.get('status')
    if new_status != old_status:
        track_file_status_change(kwargs['instance'])


def track_file_status_change(file_):
    statsd.incr('file_status_change.all.status_{}'.format(file_.status))


class FileUpload(ModelBase):
    """Created when a file is uploaded for validation/submission."""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    path = models.CharField(max_length=255, default='')
    name = models.CharField(max_length=255, default='',
                            help_text="The user's original filename")
    hash = models.CharField(max_length=255, default='')
    user = models.ForeignKey(
        'users.UserProfile', null=True, on_delete=models.CASCADE)
    valid = models.BooleanField(default=False)
    validation = models.TextField(null=True)
    automated_signing = models.BooleanField(default=False)
    compat_with_app = models.PositiveIntegerField(
        choices=amo.APPS_CHOICES, db_column='compat_with_app_id', null=True)
    compat_with_appver = models.ForeignKey(
        AppVersion, null=True, related_name='uploads_compat_for_appver',
        on_delete=models.CASCADE)
    # Not all FileUploads will have a version and addon but it will be set
    # if the file was uploaded using the new API.
    version = models.CharField(max_length=255, null=True)
    addon = models.ForeignKey(
        'addons.Addon', null=True, on_delete=models.CASCADE)
    access_token = models.CharField(max_length=40, null=True)
    ip_address = models.CharField(max_length=45, null=True, default=None)
    source = models.PositiveSmallIntegerField(
        choices=amo.UPLOAD_SOURCE_CHOICES, default=None, null=True)

    objects = ManagerBase()

    class Meta(ModelBase.Meta):
        db_table = 'file_uploads'
        indexes = [
            models.Index(fields=('compat_with_app',),
                         name='file_uploads_afe99c5e'),
        ]
        constraints = [
            models.UniqueConstraint(fields=('uuid',), name='uuid'),
        ]

    def __str__(self):
        return str(self.uuid.hex)

    def save(self, *args, **kw):
        if self.validation:
            if self.load_validation()['errors'] == 0:
                self.valid = True
        if not self.access_token:
            self.access_token = self.generate_access_token()
        super(FileUpload, self).save(*args, **kw)

    def add_file(self, chunks, filename, size):
        if not self.uuid:
            self.uuid = self._meta.get_field('uuid')._create_uuid()

        filename = force_text(u'{0}_{1}'.format(self.uuid.hex, filename))
        loc = os.path.join(user_media_path('addons'), 'temp', uuid.uuid4().hex)
        base, ext = os.path.splitext(filename)
        is_crx = False

        # Change a ZIP to an XPI, to maintain backward compatibility
        # with older versions of Firefox and to keep the rest of the XPI code
        # path as consistent as possible for ZIP uploads.
        # See: https://github.com/mozilla/addons-server/pull/2785
        if ext == '.zip':
            ext = '.xpi'

        # If the extension is a CRX, we need to do some actual work to it
        # before we just convert it to an XPI. We strip the header from the
        # CRX, then it's good; see more about the CRX file format here:
        # https://developer.chrome.com/extensions/crx
        if ext == '.crx':
            ext = '.xpi'
            is_crx = True

        if ext in amo.VALID_ADDON_FILE_EXTENSIONS:
            loc += ext

        log.info('UPLOAD: %r (%s bytes) to %r' % (filename, size, loc),
                 extra={'email': (self.user.email
                                  if self.user and self.user.email else '')})
        if is_crx:
            hash_func = write_crx_as_xpi(chunks, loc)
        else:
            hash_func = hashlib.sha256()
            with storage.open(loc, 'wb') as file_destination:
                for chunk in chunks:
                    hash_func.update(chunk)
                    file_destination.write(chunk)
        self.path = loc
        self.name = filename
        self.hash = 'sha256:%s' % hash_func.hexdigest()
        self.save()

    def generate_access_token(self):
        """
        Returns an access token used to secure download URLs.
        """
        return get_random_string(40)

    def get_authenticated_download_url(self):
        """
        Returns a download URL containing an access token bound to this file.
        """
        absolute_url = urljoin(
            settings.EXTERNAL_SITE_URL,
            reverse('files.serve_file_upload', kwargs={'uuid': self.uuid.hex})
        )
        return '{}?access_token={}'.format(absolute_url, self.access_token)

    @classmethod
    def from_post(cls, chunks, filename, size, **params):
        upload = FileUpload(**params)
        upload.add_file(chunks, filename, size)
        return upload

    @property
    def processed(self):
        return bool(self.valid or self.validation)

    @property
    def validation_timeout(self):
        if self.processed:
            validation = self.load_validation()
            messages = validation['messages']
            timeout_id = ['validator',
                          'unexpected_exception',
                          'validation_timeout']
            return any(msg['id'] == timeout_id for msg in messages)
        else:
            return False

    @property
    def processed_validation(self):
        """Return processed validation results as expected by the frontend."""
        if self.validation:
            # Import loop.
            from olympia.devhub.utils import process_validation

            validation = self.load_validation()
            is_compatibility = self.compat_with_app is not None

            return process_validation(
                validation,
                is_compatibility=is_compatibility,
                file_hash=self.hash)

    @property
    def passed_all_validations(self):
        return self.processed and self.valid

    def load_validation(self):
        return json.loads(self.validation)

    @property
    def pretty_name(self):
        parts = self.name.split('_', 1)
        if len(parts) > 1:
            return parts[1]
        return self.name


class FileValidation(ModelBase):
    id = PositiveAutoField(primary_key=True)
    file = models.OneToOneField(
        File, related_name='validation', on_delete=models.CASCADE)
    valid = models.BooleanField(default=False)
    errors = models.IntegerField(default=0)
    warnings = models.IntegerField(default=0)
    notices = models.IntegerField(default=0)
    validation = models.TextField()

    class Meta:
        db_table = 'file_validation'

    @classmethod
    def from_json(cls, file, validation):
        if isinstance(validation, str):
            validation = json.loads(validation)

        if 'metadata' in validation:
            if (validation['metadata'].get('contains_binary_extension') or
                    validation['metadata'].get('contains_binary_content')):
                file.update(binary=True)

            if validation['metadata'].get('binary_components'):
                file.update(binary_components=True)

        # Delete any past results.
        # We most often wind up with duplicate results when multiple requests
        # for the same validation data are POSTed at the same time, which we
        # currently do not have the ability to track.
        cls.objects.filter(file=file).delete()

        return cls.objects.create(
            file=file,
            validation=json.dumps(validation),
            errors=validation['errors'],
            warnings=validation['warnings'],
            notices=validation['notices'],
            valid=validation['errors'] == 0)

    @property
    def processed_validation(self):
        """Return processed validation results as expected by the frontend."""
        # Import loop.
        from olympia.devhub.utils import process_validation
        return process_validation(
            json.loads(self.validation),
            file_hash=self.file.original_hash,
            channel=self.file.version.channel)


class WebextPermission(ModelBase):
    NATIVE_MESSAGING_NAME = u'nativeMessaging'
    permissions = JSONField(default={})
    file = models.OneToOneField('File', related_name='_webext_permissions',
                                on_delete=models.CASCADE)

    class Meta:
        db_table = 'webext_permissions'


def nfd_str(u):
    """Uses NFD to normalize unicode strings."""
    if isinstance(u, str):
        return unicodedata.normalize('NFD', u).encode('utf-8')
    return u
