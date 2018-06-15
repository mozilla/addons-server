import hashlib
import json
import os
import posixpath
import re
import time
import unicodedata
import uuid
import zipfile

from collections import namedtuple

from django.core.files.storage import default_storage as storage
from django.db import models
from django.dispatch import receiver
from django.template.defaultfilters import slugify
from django.utils.encoding import force_bytes, force_text
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.translation import ugettext, ugettext_lazy as _

from django_extensions.db.fields.json import JSONField
from django_statsd.clients import statsd
from jinja2 import escape as jinja2_escape

import olympia.core.logger

from olympia import amo
from olympia.lib.cache import memoize
from olympia.amo.decorators import use_master
from olympia.amo.models import ModelBase, OnChangeMixin, UncachedManagerBase
from olympia.amo.storage_utils import copy_stored_file, move_stored_file
from olympia.amo.templatetags.jinja_helpers import (
    absolutify, urlparams, user_media_path, user_media_url)
from olympia.amo.urlresolvers import reverse
from olympia.applications.models import AppVersion
from olympia.files.utils import SafeZip, write_crx_as_xpi
from olympia.translations.fields import TranslatedField


log = olympia.core.logger.getLogger('z.files')

# Acceptable extensions.
EXTENSIONS = ('.crx', '.xpi', '.jar', '.xml', '.json', '.zip')


class File(OnChangeMixin, ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES_FILE

    version = models.ForeignKey(
        'versions.Version', related_name='files',
        on_delete=models.CASCADE)
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
    status = models.PositiveSmallIntegerField(
        choices=STATUS_CHOICES.items(), default=amo.STATUS_AWAITING_REVIEW)
    datestatuschanged = models.DateTimeField(null=True, auto_now_add=True)
    is_restart_required = models.BooleanField(default=False)
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
        return absolutify(urlparams(url, src=src))

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
        upload.path = force_bytes(nfd_str(upload.path))
        ext = os.path.splitext(upload.path)[1]
        if ext == '.jar':
            ext = '.xpi'
        file_.filename = file_.generate_filename(extension=ext or '.xpi')
        # Size in bytes.
        file_.size = storage.size(upload.path)
        data = cls.get_jetpack_metadata(upload.path)
        if 'sdkVersion' in data and data['sdkVersion']:
            file_.jetpack_version = data['sdkVersion'][:10]
        file_.is_restart_required = parsed_data.get(
            'is_restart_required', False)
        file_.strict_compatibility = parsed_data.get(
            'strict_compatibility', False)
        file_.is_multi_package = parsed_data.get('is_multi_package', False)
        file_.is_experiment = parsed_data.get('is_experiment', False)
        file_.is_webextension = parsed_data.get('is_webextension', False)
        file_.is_mozilla_signed_extension = parsed_data.get(
            'is_mozilla_signed_extension', False)

        file_.hash = file_.generate_hash(upload.path)
        file_.original_hash = file_.hash

        if upload.validation:
            validation = json.loads(upload.validation)
            if validation['metadata'].get('requires_chrome'):
                file_.requires_chrome = True

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
        copy_stored_file(
            upload.path,
            os.path.join(version.path_prefix, nfd_str(file_.filename)))

        if upload.validation:
            FileValidation.from_json(file_, validation)

        return file_

    @classmethod
    def get_jetpack_metadata(cls, path):
        data = {'sdkVersion': None}
        try:
            zip_ = zipfile.ZipFile(path)
        except (zipfile.BadZipfile, IOError):
            # This path is not an XPI. It's probably an app manifest.
            return data
        if 'package.json' in zip_.namelist():
            data['sdkVersion'] = "jpm"
        else:
            name = 'harness-options.json'
            if name in zip_.namelist():
                try:
                    opts = json.load(zip_.open(name))
                except ValueError as exc:
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
            msg = 'Move Failure: %s %s' % (force_bytes(src), force_bytes(dst))
            log.error(msg)

    def hide_disabled_file(self):
        """Move a disabled file to the guarded file path."""
        if not self.filename:
            return
        src, dst = self.file_path, self.guarded_file_path
        self.mv(src, dst, 'Moving disabled file: %s => %s')

    def unhide_disabled_file(self):
        if not self.filename:
            return
        src, dst = self.guarded_file_path, self.file_path
        self.mv(src, dst, 'Moving undisabled file: %s => %s')

    _get_localepicker = re.compile('^locale browser ([\w\-_]+) (.*)$', re.M)

    @memoize(prefix='localepicker', time=None)
    def get_localepicker(self):
        """
        For a file that is part of a language pack, extract
        the chrome/localepicker.properties file and return as
        a string.
        """
        start = time.time()
        zip = SafeZip(self.file_path)
        if not zip.is_valid():
            return ''

        try:
            manifest = zip.read('chrome.manifest')
        except KeyError as e:
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
        except (zipfile.BadZipfile, IOError) as e:
            log.error('Error unzipping: %s, %s in file: %s' % (p, e, self.pk))
            return ''
        except (ValueError, KeyError) as e:
            log.error('No file named: %s in file: %s' % (e, self.pk))
            return ''

        end = time.time() - start
        log.info('Extracted localepicker file: %s in %.2fs' %
                 (self.pk, end))
        statsd.timing('files.extract.localepicker', (end * 1000))
        return res

    @property
    def webext_permissions(self):
        """Return permissions that should be displayed, with descriptions, in
        defined order:
        1) Either the match all permission, if present (e.g. <all-urls>), or
           match urls for sites (<all-urls> takes preference over match urls)
        2) nativeMessaging permission, if present
        3) other known permissions in alphabetical order
        """
        knowns = list(WebextPermissionDescription.objects.filter(
            name__in=self.webext_permissions_list).iterator())

        urls = []
        match_url = None
        for name in self.webext_permissions_list:
            if re.match(WebextPermissionDescription.MATCH_ALL_REGEX, name):
                match_url = WebextPermissionDescription.ALL_URLS_PERMISSION
            elif name == WebextPermission.NATIVE_MESSAGING_NAME:
                # Move nativeMessaging to front of the list
                for index, perm in enumerate(knowns):
                    if perm.name == WebextPermission.NATIVE_MESSAGING_NAME:
                        knowns.pop(index)
                        knowns.insert(0, perm)
                        break
            elif '//' in name:
                # Filter out match urls so we can group them.
                urls.append(name)
            # Other strings are unknown permissions we don't care about

        if match_url is None and len(urls) == 1:
            match_url = Permission(
                u'single-match',
                ugettext(u'Access your data for {name}')
                .format(name=urls[0]))
        elif match_url is None and len(urls) > 1:
            details = (u'<details><summary>{copy}</summary><ul>{sites}</ul>'
                       u'</details>')
            copy = ugettext(u'Access your data on the following websites:')
            sites = ''.join(
                [u'<li>%s</li>' % jinja2_escape(name) for name in urls])
            match_url = Permission(
                u'multiple-match',
                mark_safe(details.format(copy=copy, sites=sites)))

        return ([match_url] if match_url else []) + knowns

    @cached_property
    def webext_permissions_list(self):
        if not self.is_webextension:
            return []
        try:
            # Filter out any errant non-strings included in the manifest JSON.
            # Remove any duplicate permissions.
            permissions = set()
            permissions = [p for p in self._webext_permissions.permissions
                           if isinstance(p, basestring) and not
                           (p in permissions or permissions.add(p))]
            return permissions

        except WebextPermission.DoesNotExist:
            return []


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

    if (file_.jetpack_version and
            not file_.is_restart_required and
            not file_.requires_chrome):
        statsd.incr('file_status_change.jetpack_sdk_only.status_{}'
                    .format(file_.status))


class FileUpload(ModelBase):
    """Created when a file is uploaded for validation/submission."""
    uuid = models.UUIDField(default=uuid.uuid4, editable=False)
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

    objects = UncachedManagerBase()

    class Meta(ModelBase.Meta):
        db_table = 'file_uploads'

    def __unicode__(self):
        return unicode(self.uuid.hex)

    def save(self, *args, **kw):
        if self.validation:
            if self.load_validation()['errors'] == 0:
                self.valid = True
        super(FileUpload, self).save(*args, **kw)

    def add_file(self, chunks, filename, size):
        if not self.uuid:
            self.uuid = self._meta.get_field('uuid')._create_uuid()

        filename = force_bytes(u'{0}_{1}'.format(self.uuid.hex, filename))
        loc = os.path.join(user_media_path('addons'), 'temp', uuid.uuid4().hex)
        base, ext = os.path.splitext(force_bytes(filename))
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

        if ext in EXTENSIONS:
            loc += ext

        log.info('UPLOAD: %r (%s bytes) to %r' % (filename, size, loc))
        if is_crx:
            hash = write_crx_as_xpi(chunks, storage, loc)
        else:
            hash = hashlib.sha256()
            with storage.open(loc, 'wb') as file_destination:
                for chunk in chunks:
                    hash.update(chunk)
                    file_destination.write(chunk)
        self.path = loc
        self.name = filename
        self.hash = 'sha256:%s' % hash.hexdigest()
        self.save()

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

            return process_validation(validation, is_compatibility, self.hash)

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
    file = models.OneToOneField(File, related_name='validation')
    valid = models.BooleanField(default=False)
    errors = models.IntegerField(default=0)
    warnings = models.IntegerField(default=0)
    notices = models.IntegerField(default=0)
    validation = models.TextField()

    class Meta:
        db_table = 'file_validation'

    @classmethod
    def from_json(cls, file, validation):
        if isinstance(validation, basestring):
            validation = json.loads(validation)
        new = cls(file=file, validation=json.dumps(validation),
                  errors=validation['errors'],
                  warnings=validation['warnings'],
                  notices=validation['notices'],
                  valid=validation['errors'] == 0)

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
        from olympia.devhub.utils import process_validation
        return process_validation(json.loads(self.validation),
                                  file_hash=self.file.original_hash)


class WebextPermission(ModelBase):
    NATIVE_MESSAGING_NAME = u'nativeMessaging'
    permissions = JSONField(default={})
    file = models.OneToOneField('File', related_name='_webext_permissions',
                                on_delete=models.CASCADE)

    class Meta:
        db_table = 'webext_permissions'


Permission = namedtuple('Permission',
                        'name, description')


class WebextPermissionDescription(ModelBase):
    MATCH_ALL_REGEX = r'^\<all_urls\>|(\*|http|https):\/\/\*\/'
    ALL_URLS_PERMISSION = Permission(
        u'all_urls',
        _(u'Access your data for all websites')
    )
    name = models.CharField(max_length=255, unique=True)
    description = TranslatedField()

    class Meta:
        db_table = 'webext_permission_descriptions'
        ordering = ['name']


def nfd_str(u):
    """Uses NFD to normalize unicode strings."""
    if isinstance(u, unicode):
        return unicodedata.normalize('NFD', u).encode('utf-8')
    return u
