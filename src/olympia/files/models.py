import hashlib
import json
import os
import re
import uuid

from urllib.parse import urljoin

from django.conf import settings
from django.core.files import File as DjangoFile
from django.core.files.storage import default_storage as storage
from django.db import models
from django.dispatch import receiver
from django.urls import reverse
from django.utils.translation import gettext
from django.utils.crypto import get_random_string
from django.utils.encoding import force_str
from django.utils.functional import cached_property
from django.utils.text import slugify

from django_statsd.clients import statsd

import olympia.core.logger

from olympia import amo, core
from olympia.amo.decorators import use_primary_db
from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import ManagerBase, ModelBase, OnChangeMixin
from olympia.amo.utils import id_to_path, SafeStorage
from olympia.files.utils import (
    get_sha256,
    InvalidOrUnsupportedCrx,
    write_crx_as_xpi,
)


log = olympia.core.logger.getLogger('z.files')


def files_upload_to_callback(instance, filename):
    """upload_to callback for File instances.

    When <File instance>.save() is called, that triggers a call to this
    function if the underlying <File instance>.file had not yet been
    "committed" to the filesystem - typically when we're assigned it but not
    called saved yet.

    For new uploads, the returned path is:
    {directories}/{addon_slug}-{version}.{extension}, where {directories} is
    {addon_id last 2 digits}/{addon_id last 4 digits}/{addon_id}. We drop all
    non-ascii chars from the slug, and if the result is empty, fall back on the
    addon id.

    By convention, newly signed files after 2022-03-31 get a .xpi extension,
    unsigned get .zip. This helps ensure CDN cache is busted when we sign
    something.

    Note that per Django requirements this gets passed the object instance and
    a filename, but the filename is completely ignored here (it's meant to
    represent the user-provided filename in user uploads).
    """
    # Start with the add-on slug, but make it go through django's slugify() to
    # drop unicode characters.
    name = (
        instance.addon.slug and slugify(instance.addon.slug).replace('-', '_')
    ) or str(instance.addon.pk)
    parts = (name, instance.version.version)
    file_extension = '.xpi' if instance.is_signed else '.zip'
    return os.path.join(
        id_to_path(instance.addon.pk, breadth=2), '-'.join(parts) + file_extension
    )


def files_storage():
    return SafeStorage(root_setting='ADDONS_PATH')


class File(OnChangeMixin, ModelBase):
    id = PositiveAutoField(primary_key=True)
    STATUS_CHOICES = amo.STATUS_CHOICES_FILE
    SUPPORTED_MANIFEST_VERSIONS = ((2, 'Manifest V2'), (3, 'Manifest V3'))

    version = models.OneToOneField('versions.Version', on_delete=models.CASCADE)
    file = models.FileField(
        max_length=255,
        default='',
        db_column='filename',
        storage=files_storage,
        upload_to=files_upload_to_callback,
    )
    size = models.PositiveIntegerField(default=0)  # In bytes.
    hash = models.CharField(max_length=255, default='')
    # The original hash of the file, before we sign it, or repackage it in
    # any other way.
    original_hash = models.CharField(max_length=255, default='')
    status = models.PositiveSmallIntegerField(
        choices=STATUS_CHOICES.items(), default=amo.STATUS_AWAITING_REVIEW
    )
    datestatuschanged = models.DateTimeField(null=True, auto_now_add=True)
    strict_compatibility = models.BooleanField(default=False)
    approval_date = models.DateTimeField(null=True)
    # Serial number of the certificate use for the signature.
    cert_serial_num = models.TextField(blank=True)
    # Is the file signed by Mozilla?
    is_signed = models.BooleanField(default=False)
    # Is the file an experiment (see bug 1220097)?
    is_experiment = models.BooleanField(default=False)
    # Is the file a special "Mozilla Signed Extension"
    # see https://wiki.mozilla.org/Add-ons/InternalSigning
    is_mozilla_signed_extension = models.BooleanField(default=False)
    # The user has disabled this file and this was its status.
    # STATUS_NULL means the user didn't disable the File - i.e. Mozilla did.
    original_status = models.PositiveSmallIntegerField(default=amo.STATUS_NULL)
    # The manifest_version defined in manifest.json
    manifest_version = models.SmallIntegerField(choices=SUPPORTED_MANIFEST_VERSIONS)

    class Meta(ModelBase.Meta):
        db_table = 'files'
        indexes = [
            models.Index(fields=('created', 'version'), name='created_idx'),
            models.Index(
                fields=('datestatuschanged', 'version'), name='statuschanged_idx'
            ),
            models.Index(fields=('status',), name='status'),
        ]

    def __str__(self):
        return str(self.id)

    @property
    def has_been_validated(self):
        try:
            self.validation
        except FileValidation.DoesNotExist:
            return False
        else:
            return True

    def get_url_path(self, attachment=False):
        # We allow requests to not specify a filename, but it's mandatory that
        # we include it in our responses, because Fenix intercepts the
        # downloads using a regex and expects the filename to be part of the
        # URL - it even wants the filename to end with `.xpi` - though it
        # doesn't care about what's after the path, so any query string is ok.
        # See https://github.com/mozilla-mobile/fenix/blob/
        # 07d43971c0767fc023996dc32eb73e3e37c6517a/app/src/main/java/org/mozilla/fenix/
        # AppRequestInterceptor.kt#L173
        kwargs = {'file_id': self.pk, 'filename': self.pretty_filename}
        if attachment:
            kwargs['download_type'] = 'attachment'
        return reverse('downloads.file', kwargs=kwargs)

    @classmethod
    def from_upload(cls, upload, version, parsed_data=None):
        """
        Create a File instance from a FileUpload, a Version and the parsed_data
        generated by parse_addon().

        Note that it's the caller's responsability to ensure the file is valid.
        We can't check for that here because an admin may have overridden the
        validation results."""
        assert parsed_data is not None

        file_ = cls(version=version)
        upload_path = force_str(upload.path)
        # Size in bytes.
        file_.size = storage.size(upload_path)
        file_.strict_compatibility = parsed_data.get('strict_compatibility', False)
        file_.is_experiment = parsed_data.get('is_experiment', False)
        file_.is_mozilla_signed_extension = parsed_data.get(
            'is_mozilla_signed_extension', False
        )
        file_.is_signed = file_.is_mozilla_signed_extension
        file_.hash = upload.hash
        file_.original_hash = file_.hash
        file_.manifest_version = parsed_data.get('manifest_version')
        log.info(f'New file: {file_!r} from {upload!r}')

        # FileUpload.path is not a FileField, so we have to open() the path to
        # make a DjangoFile in order to assign it to file_.file.
        with open(upload_path, 'rb') as src:
            file_.file = DjangoFile(src)
            file_.save()  # This also saves the file to the filesystem.

        permissions = list(parsed_data.get('permissions', []))
        if file_.manifest_version > 2:
            permissions = [
                perm
                for perm in permissions
                # This is the same regex that addons-frontend uses.
                # See /src/amo/components/PermissionsCard/permissions.js#L93
                if re.match(r'^(\w+)(?:\.(\w+)(?:\.\w+)*)?$', perm)
            ]
        optional_permissions = list(parsed_data.get('optional_permissions', []))
        host_permissions = (
            list(parsed_data.get('host_permissions', []))
            if file_.manifest_version > 2
            else []
        )

        # devtools_page isn't in permissions block but treated as one
        # if a custom devtools page is added by an addon
        if 'devtools_page' in parsed_data:
            permissions.append('devtools')

        # Add content_scripts host matches too.
        for script in parsed_data.get('content_scripts', []):
            permissions.extend(script.get('matches', []))
        if permissions or optional_permissions or host_permissions:
            WebextPermission.objects.create(
                permissions=permissions,
                optional_permissions=optional_permissions,
                host_permissions=host_permissions,
                file=file_,
            )

        if upload.validation:
            validation = json.loads(upload.validation)
            FileValidation.from_json(file_, validation)

        return file_

    def generate_hash(self):
        """Generate a hash for the File"""
        return f'sha256:{get_sha256(self.file)}'

    @property
    def pretty_filename(self):
        """Displayable filename."""
        return os.path.basename(self.file.name) if self.file else ''

    def latest_xpi_url(self, attachment=False):
        addon = self.addon
        extension = os.path.splitext(self.file.name)[-1] or 'xpi'
        kw = {
            'addon_id': addon.slug,
            'filename': f'addon-{addon.pk}-latest{extension}',
        }
        if attachment:
            kw['download_type'] = 'attachment'
        return reverse('downloads.latest', kwargs=kw)

    @property
    def addon(self):
        return self.version.addon

    @cached_property
    def permissions(self):
        try:
            # Filter out any errant non-strings included in the manifest JSON.
            # Remove any duplicate permissions.
            permissions = set()
            permissions = [
                p
                for p in self._webext_permissions.permissions
                if isinstance(p, str) and not (p in permissions or permissions.add(p))
            ]
            return permissions

        except WebextPermission.DoesNotExist:
            return []

    @cached_property
    def optional_permissions(self):
        try:
            # Filter out any errant non-strings included in the manifest JSON.
            # Remove any duplicate optional permissions.
            permissions = set()
            permissions = [
                p
                for p in self._webext_permissions.optional_permissions
                if isinstance(p, str) and not (p in permissions or permissions.add(p))
            ]
            return permissions

        except WebextPermission.DoesNotExist:
            return []

    @cached_property
    def host_permissions(self):
        try:
            # Filter out any errant non-strings included in the manifest JSON.
            # Remove any duplicate host permissions.
            permissions = set()
            permissions = [
                p
                for p in self._webext_permissions.host_permissions
                if isinstance(p, str) and not (p in permissions or permissions.add(p))
            ]
            return permissions

        except WebextPermission.DoesNotExist:
            return []

    def get_review_status_display(self):
        # Like .get_file_status_display but with logic to make the status more accurate
        if self.status == amo.STATUS_DISABLED:
            return (
                gettext('Rejected')
                if getattr(self, 'version', None) and self.version.human_review_date
                else gettext('Unreviewed')
            )
        return self.STATUS_CHOICES.get(
            self.status, gettext('[status:%s]') % self.status
        )


@use_primary_db
def update_status(sender, instance, **kw):
    if not kw.get('raw'):
        try:
            addon = instance.version.addon
            if 'delete' in kw:
                addon.update_status(ignore_version=instance.version)
            else:
                addon.update_status()
            instance.version.reset_due_date()
        except models.ObjectDoesNotExist:
            pass


def update_status_delete(sender, instance, **kw):
    kw['delete'] = True
    return update_status(sender, instance, **kw)


models.signals.post_save.connect(
    update_status, sender=File, dispatch_uid='version_update_status'
)
models.signals.post_delete.connect(
    update_status_delete, sender=File, dispatch_uid='version_update_status'
)


@receiver(models.signals.post_delete, sender=File, dispatch_uid='cleanup_file')
def cleanup_file(sender, instance, **kw):
    """On delete of the file object from the database, unlink the file from
    the file system"""
    try:
        if kw.get('raw') or not instance.file:
            return
        if storage.exists(instance.file.path):
            log.info(
                f'Removing filename: {instance.pretty_filename} for file: {instance.pk}'
            )
            instance.file.delete(save=False)
    except models.ObjectDoesNotExist:
        return


@File.on_change
def check_file(old_attr, new_attr, instance, sender, **kw):
    if kw.get('raw'):
        return
    # Log that the hash has changed.
    old, new = old_attr.get('hash'), instance.hash
    if old != new:
        try:
            addon = instance.version.addon.pk
        except models.ObjectDoesNotExist:
            addon = 'unknown'
        log.info(
            'Hash changed for file: %s, addon: %s, from: %s to: %s'
            % (instance.pk, addon, old, new)
        )


def track_new_status(sender, instance, *args, **kw):
    if kw.get('raw'):
        # The file is being loaded from a fixure.
        return
    if kw.get('created'):
        track_file_status_change(instance)


models.signals.post_save.connect(
    track_new_status, sender=File, dispatch_uid='track_new_file_status'
)


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
    statsd.incr(f'file_status_change.all.status_{file_.status}')


class FileUpload(ModelBase):
    """Created when a file is uploaded for validation/submission."""

    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    path = models.CharField(max_length=255, default='')
    name = models.CharField(
        max_length=255, default='', help_text="The user's original filename"
    )
    hash = models.CharField(max_length=255, default='')
    user = models.ForeignKey('users.UserProfile', on_delete=models.CASCADE)
    valid = models.BooleanField(default=False)
    validation = models.TextField(null=True)
    channel = models.PositiveSmallIntegerField(choices=amo.CHANNEL_CHOICES)
    # Not all FileUploads will have a version and addon but it will be set
    # if the file was uploaded using the new API.
    version = models.CharField(max_length=255, null=True)
    addon = models.ForeignKey('addons.Addon', null=True, on_delete=models.CASCADE)
    access_token = models.CharField(max_length=40, null=True)
    ip_address = models.CharField(max_length=45)
    source = models.PositiveSmallIntegerField(choices=amo.UPLOAD_SOURCE_CHOICES)

    objects = ManagerBase()

    class Meta(ModelBase.Meta):
        db_table = 'file_uploads'
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
        super().save(*args, **kw)

    def write_data_to_path(self, chunks):
        hash_obj = hashlib.sha256()
        with storage.open(self.path, 'wb') as file_destination:
            for chunk in chunks:
                hash_obj.update(chunk)
                file_destination.write(chunk)
        return hash_obj

    @classmethod
    def generate_path(cls, ext='.zip'):
        return os.path.join(settings.ADDONS_PATH, 'temp', f'{uuid.uuid4().hex}{ext}')

    def add_file(self, chunks, filename, size):
        if not self.uuid:
            self.uuid = self._meta.get_field('uuid')._create_uuid()

        _base, ext = os.path.splitext(filename)
        was_crx = ext == '.crx'
        # Filename we'll expose (but not use for storage).
        self.name = force_str(f'{self.uuid.hex}_{filename}')

        # Final path on our filesystem. If it had a valid extension we change
        # it to .zip (CRX files are converted before validation, so they will
        # be treated as normal .zip for validation). If somehow this is
        # not a valid archive or the extension is invalid parse_addon() will
        # eventually complain at validation time or before even reaching the
        # linter.
        if ext in amo.VALID_ADDON_FILE_EXTENSIONS:
            ext = '.zip'
        self.path = self.generate_path(ext)

        hash_obj = None
        if was_crx:
            try:
                hash_obj = write_crx_as_xpi(chunks, self.path)
            except InvalidOrUnsupportedCrx:
                # We couldn't convert the crx file. Write it to the filesystem
                # normally, the validation process should reject this with a
                # proper error later.
                pass
        if hash_obj is None:
            hash_obj = self.write_data_to_path(chunks)
        self.hash = 'sha256:%s' % hash_obj.hexdigest()

        # The following log statement is used by foxsec-pipeline.
        log.info(
            f'UPLOAD: {self.name!r} ({size} bytes) to {self.path!r}',
            extra={
                'email': (self.user.email or ''),
                'upload_hash': self.hash,
            },
        )
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
            reverse('files.serve_file_upload', kwargs={'uuid': self.uuid.hex}),
        )
        return f'{absolute_url}?access_token={self.access_token}'

    @classmethod
    def from_post(
        cls,
        chunks,
        *,
        filename,
        size,
        user,
        source,
        channel,
        addon=None,
        version=None,
    ):
        max_ip_length = cls._meta.get_field('ip_address').max_length
        ip_address = (core.get_remote_addr() or '')[:max_ip_length]
        upload = FileUpload(
            addon=addon,
            user=user,
            source=source,
            channel=channel,
            ip_address=ip_address,
            version=version,
        )
        upload.add_file(chunks, filename, size)

        # The following log statement is used by foxsec-pipeline.
        log.info('FileUpload created: %s' % upload.uuid.hex)

        return upload

    @property
    def processed(self):
        return bool(self.valid or self.validation)

    @property
    def submitted(self):
        return bool(self.addon)

    @property
    def validation_timeout(self):
        if self.processed:
            validation = self.load_validation()
            messages = validation.get('messages', [])
            timeout_id = ['validator', 'unexpected_exception', 'validation_timeout']
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

            return process_validation(validation, file_hash=self.hash)

    @property
    def passed_all_validations(self):
        return self.processed and self.valid

    def load_validation(self):
        return json.loads(self.validation or '{}')

    @property
    def pretty_name(self):
        parts = self.name.split('_', 1)
        if len(parts) > 1:
            return parts[1]
        return self.name


class FileValidation(ModelBase):
    id = PositiveAutoField(primary_key=True)
    file = models.OneToOneField(
        File, related_name='validation', on_delete=models.CASCADE
    )
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
            valid=validation['errors'] == 0,
        )

    @property
    def processed_validation(self):
        """Return processed validation results as expected by the frontend."""
        # Import loop.
        from olympia.devhub.utils import process_validation

        return process_validation(
            json.loads(self.validation),
            file_hash=self.file.original_hash,
            channel=self.file.version.channel,
        )


class WebextPermission(ModelBase):
    NATIVE_MESSAGING_NAME = 'nativeMessaging'
    permissions = models.JSONField(default=dict)
    optional_permissions = models.JSONField(default=dict)
    host_permissions = models.JSONField(default=dict)
    file = models.OneToOneField(
        'File', related_name='_webext_permissions', on_delete=models.CASCADE
    )

    class Meta:
        db_table = 'webext_permissions'
