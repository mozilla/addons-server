import hashlib
import json
import os
import posixpath
import re
import time
import unicodedata
import uuid
import zipfile

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import models
from django.dispatch import receiver
from django.template.defaultfilters import slugify
from django.utils.encoding import smart_str
from django.utils.translation import force_text

import commonware
from cache_nuggets.lib import memoize
from django_statsd.clients import statsd
from uuidfield.fields import UUIDField

import amo
import amo.models
import amo.utils
from amo.decorators import use_master
from amo.storage_utils import copy_stored_file, move_stored_file
from amo.urlresolvers import reverse
from amo.helpers import user_media_path, user_media_url
from applications.models import AppVersion
from files.utils import SafeUnzip
from tags.models import Tag

log = commonware.log.getLogger('z.files')

# Acceptable extensions.
EXTENSIONS = ('.xpi', '.jar', '.xml', '.json', '.zip')


class File(amo.models.OnChangeMixin, amo.models.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES_FILE

    version = models.ForeignKey('versions.Version', related_name='files')
    platform = models.PositiveIntegerField(
        choices=amo.SUPPORTED_PLATFORMS_CHOICES,
        default=amo.PLATFORM_ALL.id,
        db_column="platform_id"
    )
    filename = models.CharField(max_length=255, default='')
    size = models.PositiveIntegerField(default=0)  # In bytes.
    hash = models.CharField(max_length=255, default='')
    # The original hash of the file, before we sign it, or repackage it in
    # any other way.
    original_hash = models.CharField(max_length=255, default='')
    jetpack_version = models.CharField(max_length=10, null=True)
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES.items(),
                                              default=amo.STATUS_UNREVIEWED)
    datestatuschanged = models.DateTimeField(null=True, auto_now_add=True)
    no_restart = models.BooleanField(default=False)
    strict_compatibility = models.BooleanField(default=False)
    # The XPI contains JS that calls require("chrome").
    requires_chrome = models.BooleanField(default=False)
    reviewed = models.DateTimeField(null=True)
    # The `binary` field is used to store the flags from amo-validator when it
    # files files with binary extensions or files that may contain binary
    # content.
    binary = models.BooleanField(default=False)
    # The `binary_components` field is used to store the flag from
    # amo-validator when it finds "binary-components" in the chrome manifest
    # file, used for default to compatible.
    binary_components = models.BooleanField(default=False, db_index=True)
    # Serial number of the certificate use for the signature.
    cert_serial_num = models.TextField(blank=True)
    # Is the file signed by Mozilla?
    is_signed = models.BooleanField(default=False)
    # Is the file a multi-package?
    #     https://developer.mozilla.org/en-US/docs/Multiple_Item_Packaging
    is_multi_package = models.BooleanField(default=False)
    # Is the file an experiment (see bug 1220097)?
    is_experiment = models.BooleanField(default=False)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'files'

    def __unicode__(self):
        return unicode(self.id)

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
        means that either its add-on is eligible for automated signing, or
        this file is a beta version."""
        return (self.version.addon.automated_signing or
                self.status == amo.STATUS_BETA)

    def is_mirrorable(self):
        return self.status in amo.MIRROR_STATUSES

    def has_been_copied(self):
        """Checks if file has been copied to mirror"""
        if not self.mirror_file_path:
            return False
        return storage.exists(self.mirror_file_path)

    def can_be_perf_tested(self):
        """True if it's okay to run performance tests on this addon file.
        """
        is_eligible = (self.status in amo.REVIEWED_STATUSES and
                       not self.version.addon.disabled_by_user)
        return is_eligible

    def get_mirror(self, addon, attachment=False):
        if attachment:
            host = posixpath.join(user_media_url('addons'), '_attachments')
        elif addon.is_disabled or self.status == amo.STATUS_DISABLED:
            host = settings.PRIVATE_MIRROR_URL
        else:
            host = user_media_url('addons')

        return posixpath.join(*map(smart_str, [host, addon.id, self.filename]))

    def get_url_path(self, src):
        return self._make_download_url('downloads.file', src)

    def get_signed_url(self, src):
        return self._make_download_url('signing.file', src)

    def _make_download_url(self, view_name, src):
        from amo.helpers import urlparams, absolutify
        url = os.path.join(reverse(view_name, args=[self.pk]),
                           self.filename)
        return absolutify(urlparams(url, src=src))

    @classmethod
    def from_upload(cls, upload, version, platform, is_beta=False,
                    parse_data={}):
        addon = version.addon

        file_ = cls(version=version, platform=platform)
        upload.path = amo.utils.smart_path(nfd_str(upload.path))
        ext = os.path.splitext(upload.path)[1]
        if ext == '.jar':
            ext = '.xpi'
        file_.filename = file_.generate_filename(extension=ext or '.xpi')
        # Size in bytes.
        file_.size = storage.size(upload.path)
        data = cls.get_jetpack_metadata(upload.path)
        if 'sdkVersion' in data and data['sdkVersion']:
            file_.jetpack_version = data['sdkVersion'][:10]
        if file_.jetpack_version:
            Tag(tag_text='jetpack').save_tag(addon)
        file_.no_restart = parse_data.get('no_restart', False)
        file_.strict_compatibility = parse_data.get('strict_compatibility',
                                                    False)
        file_.is_multi_package = parse_data.get('is_multi_package', False)
        file_.is_experiment = parse_data.get('is_experiment', False)

        if is_beta and addon.status == amo.STATUS_PUBLIC:
            file_.status = amo.STATUS_BETA
        elif addon.trusted:
            # New files in trusted add-ons automatically receive the correct
            # approved status for their review class.
            if addon.status == amo.STATUS_PUBLIC:
                file_.status = amo.STATUS_PUBLIC
            elif addon.status in amo.LITE_STATUSES:
                file_.status = amo.STATUS_LITE

        file_.hash = file_.generate_hash(upload.path)
        file_.original_hash = file_.hash

        if upload.validation:
            validation = json.loads(upload.validation)
            if validation['metadata'].get('requires_chrome'):
                file_.requires_chrome = True

        file_.save()

        log.debug('New file: %r from %r' % (file_, upload))
        # Move the uploaded file from the temp location.
        destinations = [version.path_prefix]
        if file_.status in amo.MIRROR_STATUSES:
            destinations.append(version.mirror_path_prefix)
        for dest in destinations:
            copy_stored_file(upload.path,
                             os.path.join(dest, nfd_str(file_.filename)))

        if upload.validation:
            # Import loop.
            from devhub.tasks import annotate_validation_results
            from devhub.utils import ValidationAnnotator

            validation = annotate_validation_results(validation)
            FileValidation.from_json(file_, validation)

            # Copy annotations from any previously approved file.
            ValidationAnnotator(file_).update_annotations()

        return file_

    @classmethod
    def get_jetpack_metadata(cls, path):
        data = {'sdkVersion': None}
        try:
            zip_ = zipfile.ZipFile(path)
        except (zipfile.BadZipfile, IOError):
            # This path is not an XPI. It's probably an app manifest.
            return data
        name = 'harness-options.json'
        if name in zip_.namelist():
            try:
                opts = json.load(zip_.open(name))
            except ValueError, exc:
                log.info('Could not parse harness-options.json in %r: %s' %
                         (path, exc))
            else:
                data['sdkVersion'] = opts.get('sdkVersion')
        return data

    def generate_hash(self, filename=None):
        """Generate a hash for a file."""
        hash = hashlib.sha256()
        with open(filename or self.file_path, 'rb') as obj:
            for chunk in iter(lambda: obj.read(1024), ''):
                hash.update(chunk)
        return 'sha256:%s' % hash.hexdigest()

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

        if self.version.compatible_apps:
            apps = '+'.join([a.shortername for a in
                             self.version.compatible_apps])
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

    def latest_xpi_url(self, beta=False):
        addon = self.version.addon
        kw = {'addon_id': addon.pk, 'beta': '-beta' if beta else ''}
        if self.platform != amo.PLATFORM_ALL.id:
            kw['platform'] = self.platform
        return os.path.join(reverse('downloads.latest', kwargs=kw),
                            'addon-%s-latest%s' % (addon.pk, self.extension))

    def eula_url(self):
        return reverse('addons.eula', args=[self.version.addon_id, self.id])

    @property
    def file_path(self):
        return os.path.join(user_media_path('addons'),
                            str(self.version.addon_id),
                            self.filename)

    @property
    def addon(self):
        return self.version.addon

    @property
    def mirror_file_path(self):
        return os.path.join(user_media_path('addons'),
                            str(self.version.addon_id), self.filename)

    @property
    def guarded_file_path(self):
        return os.path.join(user_media_path('guarded_addons'),
                            str(self.version.addon_id), self.filename)

    @property
    def current_file_path(self):
        """Returns the current path of the file, whether or not it is
        guarded."""

        return (self.guarded_file_path if self.status == amo.STATUS_DISABLED
                else self.file_path)

    @property
    def extension(self):
        return os.path.splitext(self.filename)[-1]

    @classmethod
    def mv(cls, src, dst, msg):
        """Move a file from src to dst."""
        try:
            if storage.exists(src):
                log.info(msg % (src, dst))
                move_stored_file(src, dst)
        except UnicodeEncodeError:
            log.error('Move Failure: %s %s' % (smart_str(src), smart_str(dst)))

    def hide_disabled_file(self):
        """Move a disabled file to the guarded file path."""
        if not self.filename:
            return
        src, dst = self.file_path, self.guarded_file_path
        self.mv(src, dst, 'Moving disabled file: %s => %s')
        # Remove the file from the mirrors if necessary.
        if (self.mirror_file_path and
                storage.exists(smart_str(self.mirror_file_path))):
            log.info('Unmirroring disabled file: %s'
                     % self.mirror_file_path)
            storage.delete(smart_str(self.mirror_file_path))

    def unhide_disabled_file(self):
        if not self.filename:
            return
        src, dst = self.guarded_file_path, self.file_path
        self.mv(src, dst, 'Moving undisabled file: %s => %s')
        # Put files back on the mirrors if necessary.
        if storage.exists(self.file_path):
            destinations = [self.version.path_prefix]
            if self.status in amo.MIRROR_STATUSES:
                destinations.append(self.version.mirror_path_prefix)
            for dest in destinations:
                dest = os.path.join(dest, nfd_str(self.filename))
                log.info('Re-mirroring disabled/enabled file to %s' % dest)
                copy_stored_file(self.file_path, dest)

    def copy_to_mirror(self):
        if not self.filename:
            return
        try:
            if storage.exists(self.file_path):
                dst = self.mirror_file_path
                if not dst:
                    return

                log.info('Moving file to mirror: %s => %s'
                         % (self.file_path, dst))
                copy_stored_file(self.file_path, dst)
        except UnicodeEncodeError:
            log.info('Copy Failure: %s %s %s' %
                     (self.id, smart_str(self.filename),
                      smart_str(self.file_path)))

    _get_localepicker = re.compile('^locale browser ([\w\-_]+) (.*)$', re.M)

    @memoize(prefix='localepicker', time=None)
    def get_localepicker(self):
        """
        For a file that is part of a language pack, extract
        the chrome/localepicker.properties file and return as
        a string.
        """
        start = time.time()
        zip = SafeUnzip(self.file_path)
        if not zip.is_valid(fatal=False):
            return ''

        try:
            manifest = zip.extract_path('chrome.manifest')
        except KeyError, e:
            log.info('No file named: chrome.manifest in file: %s' % self.pk)
            return ''

        res = self._get_localepicker.search(manifest)
        if not res:
            log.error('Locale browser not in chrome.manifest: %s' % self.pk)
            return ''

        try:
            p = res.groups()[1]
            if 'localepicker.properties' not in p:
                p = os.path.join(p, 'localepicker.properties')
            res = zip.extract_from_manifest(p)
        except (zipfile.BadZipfile, IOError), e:
            log.error('Error unzipping: %s, %s in file: %s' % (p, e, self.pk))
            return ''
        except (ValueError, KeyError), e:
            log.error('No file named: %s in file: %s' % (e, self.pk))
            return ''

        end = time.time() - start
        log.info('Extracted localepicker file: %s in %.2fs' %
                 (self.pk, end))
        statsd.timing('files.extract.localepicker', (end * 1000))
        return res


@receiver(models.signals.post_save, sender=File,
          dispatch_uid='cache_localpicker')
def cache_localepicker(sender, instance, **kw):
    if kw.get('raw') or not kw.get('created'):
        return

    try:
        addon = instance.version.addon
    except models.ObjectDoesNotExist:
        return

    if addon.type == amo.ADDON_LPAPP and addon.status == amo.STATUS_PUBLIC:
        log.info('Updating localepicker for file: %s, addon: %s' %
                 (instance.pk, addon.pk))
        instance.get_localepicker()


@use_master
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
    for path in ('file_path', 'mirror_file_path', 'guarded_file_path'):
        try:
            filename = getattr(instance, path)
        except models.ObjectDoesNotExist:
            return
        if storage.exists(filename):
            log.info('Removing filename: %s for file: %s'
                     % (filename, instance.pk))
            storage.delete(filename)

    if not (File.objects.filter(original_hash=instance.original_hash)
            .exclude(pk=instance.pk).exists()):
        # This is the last remaining file with this hash.
        # Delete any validation annotations keyed to it.
        ValidationAnnotation.objects.filter(
            file_hash=instance.original_hash).delete()


@File.on_change
def check_file(old_attr, new_attr, instance, sender, **kw):
    if kw.get('raw'):
        return
    old, new = old_attr.get('status'), instance.status
    if new == amo.STATUS_DISABLED and old != amo.STATUS_DISABLED:
        instance.hide_disabled_file()
    elif old == amo.STATUS_DISABLED and new != amo.STATUS_DISABLED:
        instance.unhide_disabled_file()
    elif (new in amo.MIRROR_STATUSES and old not in amo.MIRROR_STATUSES):
        instance.copy_to_mirror()

    # Log that the hash has changed.
    old, new = old_attr.get('hash'), instance.hash
    if old != new:
        try:
            addon = instance.version.addon.pk
        except models.ObjectDoesNotExist:
            addon = 'unknown'
        log.info('Hash changed for file: %s, addon: %s, from: %s to: %s' %
                 (instance.pk, addon, old, new))


@File.on_change
def clear_d2c_version(old_attr, new_attr, instance, sender, **kw):
    do_clear = False
    fields = ['status', 'strict_compatibility', 'binary_components']

    for field in fields:
        if old_attr[field] != new_attr[field]:
            do_clear = True

    if do_clear:
        instance.version.addon.invalidate_d2c_versions()


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
def track_status_change(old_attr={}, new_attr={}, **kw):
    new_status = new_attr.get('status')
    old_status = old_attr.get('status')
    if new_status != old_status:
        track_file_status_change(kw['instance'])


def track_file_status_change(file_):
    statsd.incr('file_status_change.all.status_{}'.format(file_.status))

    if (file_.jetpack_version and
            file_.no_restart and
            not file_.requires_chrome):
        # These files are easier to review and typically go into the
        # "fast queue"
        statsd.incr('file_status_change.jetpack_sdk_only.status_{}'
                    .format(file_.status))


# TODO(davedash): Get rid of this table once /editors is on zamboni
class Approval(amo.models.ModelBase):

    reviewtype = models.CharField(max_length=10, default='pending')
    action = models.IntegerField(default=0)
    os = models.CharField(max_length=255, default='')
    applications = models.CharField(max_length=255, default='')
    comments = models.TextField(null=True)

    addon = models.ForeignKey('addons.Addon')
    user = models.ForeignKey('users.UserProfile')
    file = models.ForeignKey(File)
    reply_to = models.ForeignKey('self', null=True, db_column='reply_to')

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'approvals'
        ordering = ('-created',)


class FileUpload(amo.models.ModelBase):
    """Created when a file is uploaded for validation/submission."""
    uuid = UUIDField(primary_key=True, auto=True)
    path = models.CharField(max_length=255, default='')
    name = models.CharField(max_length=255, default='',
                            help_text="The user's original filename")
    hash = models.CharField(max_length=255, default='')
    user = models.ForeignKey('users.UserProfile', null=True)
    valid = models.BooleanField(default=False)
    validation = models.TextField(null=True)
    automated_signing = models.BooleanField(default=False)
    compat_with_app = models.PositiveIntegerField(
        choices=amo.APPS_CHOICES, db_column="compat_with_app_id", null=True)
    compat_with_appver = models.ForeignKey(
        AppVersion, null=True, related_name='uploads_compat_for_appver')
    # Not all FileUploads will have a version and addon but it will be set
    # if the file was uploaded using the new API.
    version = models.CharField(max_length=255, null=True)
    addon = models.ForeignKey('addons.Addon', null=True)

    objects = amo.models.UncachedManagerBase()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'file_uploads'

    def __unicode__(self):
        return self.uuid

    def save(self, *args, **kw):
        if self.validation:
            if self.load_validation()['errors'] == 0:
                self.valid = True
        super(FileUpload, self).save()

    def add_file(self, chunks, filename, size):
        if not self.pk:
            self.save()
        filename = smart_str(u'{0}_{1}'.format(self.pk, filename))
        loc = os.path.join(user_media_path('addons'), 'temp', uuid.uuid4().hex)
        base, ext = os.path.splitext(amo.utils.smart_path(filename))
        if ext in EXTENSIONS:
            loc += ext
        log.info('UPLOAD: %r (%s bytes) to %r' % (filename, size, loc))
        hash = hashlib.sha256()
        with storage.open(loc, 'wb') as fd:
            for chunk in chunks:
                hash.update(chunk)
                fd.write(chunk)
        self.path = loc
        self.name = filename
        self.hash = 'sha256:%s' % hash.hexdigest()
        self.save()

    @classmethod
    def from_post(cls, chunks, filename, size):
        fu = FileUpload()
        fu.add_file(chunks, filename, size)
        return fu

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
            from devhub.utils import process_validation

            validation = self.load_validation()
            is_compatibility = self.compat_with_app is not None

            return process_validation(validation, is_compatibility, self.hash)

    @property
    def passed_all_validations(self):
        return self.processed and self.valid and (
            not self.automated_signing or self.passed_auto_validation)

    @property
    def passed_auto_validation(self):
        return self.load_validation()['passed_auto_validation']

    def load_validation(self):
        return json.loads(self.validation)


class FileValidation(amo.models.ModelBase):
    file = models.OneToOneField(File, related_name='validation')
    valid = models.BooleanField(default=False)
    errors = models.IntegerField(default=0)
    warnings = models.IntegerField(default=0)
    notices = models.IntegerField(default=0)
    signing_trivials = models.IntegerField(default=0)
    signing_lows = models.IntegerField(default=0)
    signing_mediums = models.IntegerField(default=0)
    signing_highs = models.IntegerField(default=0)
    passed_auto_validation = models.BooleanField(default=False)
    validation = models.TextField()

    class Meta:
        db_table = 'file_validation'

    @classmethod
    def from_json(cls, file, validation):
        if isinstance(validation, basestring):
            validation = json.loads(validation)

        signing = validation['signing_summary']

        new = cls(file=file, validation=json.dumps(validation),
                  errors=validation['errors'],
                  warnings=validation['warnings'],
                  notices=validation['notices'],
                  valid=validation['errors'] == 0,
                  signing_trivials=signing['trivial'],
                  signing_lows=signing['low'],
                  signing_mediums=signing['medium'],
                  signing_highs=signing['high'],
                  passed_auto_validation=validation['passed_auto_validation'])

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

        new.save()
        return new

    @property
    def processed_validation(self):
        """Return processed validation results as expected by the frontend."""
        # Import loop.
        from devhub.utils import process_validation
        return process_validation(json.loads(self.validation),
                                  file_hash=self.file.original_hash)


class ValidationAnnotation(amo.models.ModelBase):
    file_hash = models.CharField(max_length=255, db_index=True)
    message_key = models.CharField(max_length=1024)
    ignore_duplicates = models.NullBooleanField(blank=True, null=True)

    class Meta:
        db_table = 'validation_annotations'


def nfd_str(u):
    """Uses NFD to normalize unicode strings."""
    if isinstance(u, unicode):
        return unicodedata.normalize('NFD', u).encode('utf-8')
    return u
