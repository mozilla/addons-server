from datetime import datetime, timedelta
import hashlib
import json
import os
import posixpath
import re
import unicodedata
import uuid
import shutil
import stat
import time
import zipfile

import django.dispatch
from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.db import models
from django.dispatch import receiver
from django.template.defaultfilters import slugify
from django.utils.encoding import smart_str

import commonware
from django_statsd.clients import statsd
from uuidfield.fields import UUIDField
import waffle

import amo
import amo.models
import amo.utils
from amo.storage_utils import copy_stored_file, move_stored_file
from amo.urlresolvers import reverse
from applications.models import Application, AppVersion
from apps.amo.utils import memoize
import devhub.signals
from files.utils import RDF, SafeUnzip
from versions.compare import version_int as vint

log = commonware.log.getLogger('z.files')

# Acceptable extensions.
EXTENSIONS = ('.xpi', '.jar', '.xml', '.webapp', '.json')


class File(amo.models.OnChangeMixin, amo.models.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()

    version = models.ForeignKey('versions.Version', related_name='files')
    platform = models.ForeignKey('Platform', default=amo.PLATFORM_ALL.id)
    filename = models.CharField(max_length=255, default='')
    size = models.PositiveIntegerField(default=0)  # kilobytes
    hash = models.CharField(max_length=255, default='')
    # TODO: delete this column
    codereview = models.BooleanField(default=False)
    jetpack_version = models.CharField(max_length=10, null=True)
    # The jetpack builder version, if applicable.
    builder_version = models.CharField(max_length=10, null=True,
                                       db_index=True)
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES,
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

    # Whether a webapp uses flash or not.
    uses_flash = models.BooleanField(default=False, db_index=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'files'

    def __unicode__(self):
        return unicode(self.id)

    @property
    def amo_platform(self):
        # TODO: Ideally this would be ``platform``.
        return amo.PLATFORMS[self.platform_id]

    @property
    def has_been_validated(self):
        try:
            self.validation
        except FileValidation.DoesNotExist:
            return False
        else:
            return True

    def is_mirrorable(self):
        if (self.version.addon_id and
            (self.version.addon.is_premium() or
             self.version.addon.type == amo.ADDON_WEBAPP)):
            return False
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
                       self.version.addon.type != amo.ADDON_WEBAPP and
                       not self.version.addon.disabled_by_user)
        return is_eligible

    def get_mirror(self, addon, attachment=False):
        if self.datestatuschanged:
            published = datetime.now() - self.datestatuschanged
        else:
            published = timedelta(minutes=0)

        if attachment:
            host = posixpath.join(settings.LOCAL_MIRROR_URL, '_attachments')
        elif addon.is_disabled or self.status == amo.STATUS_DISABLED:
            host = settings.PRIVATE_MIRROR_URL
        elif (addon.status == amo.STATUS_PUBLIC
              and not addon.disabled_by_user
              and self.status in (amo.STATUS_PUBLIC, amo.STATUS_BETA)
              and published > timedelta(minutes=settings.MIRROR_DELAY)
              and not settings.DEBUG):
            host = settings.MIRROR_URL  # Send it to the mirrors.
        else:
            host = settings.LOCAL_MIRROR_URL

        return posixpath.join(*map(smart_str, [host, addon.id, self.filename]))

    def get_url_path(self, src, addon=None):
        from amo.helpers import urlparams, absolutify
        # In most cases we have an addon in the calling context.
        if not addon:
            addon = self.version.addon
        if addon.is_premium() and addon.type != amo.ADDON_WEBAPP:
            url = reverse('downloads.watermarked', args=[self.id])
        else:
            url = reverse('downloads.file', args=[self.id])
        url = os.path.join(url, self.filename)
        # Firefox's Add-on Manager needs absolute urls.
        return absolutify(urlparams(url, src=src))

    @classmethod
    def from_upload(cls, upload, version, platform, parse_data={}):
        is_webapp = version.addon.is_webapp()
        f = cls(version=version, platform=platform)
        upload.path = amo.utils.smart_path(nfd_str(upload.path))
        f.filename = f.generate_filename(os.path.splitext(upload.path)[1])
        # Size in kilobytes.
        f.size = int(max(1, round(storage.size(upload.path) / 1024)))
        data = cls.get_jetpack_metadata(upload.path)
        f.jetpack_version = data['sdkVersion']
        f.builder_version = data['builderVersion']
        f.no_restart = parse_data.get('no_restart', False)
        f.strict_compatibility = parse_data.get('strict_compatibility', False)
        if is_webapp:
            f.status = amo.STATUS_PENDING
        elif version.addon.status == amo.STATUS_PUBLIC:
            if amo.VERSION_BETA.search(parse_data.get('version', '')):
                f.status = amo.STATUS_BETA
            elif version.addon.trusted:
                f.status = amo.STATUS_PUBLIC
        elif (version.addon.status in amo.LITE_STATUSES
              and version.addon.trusted):
            f.status = version.addon.status
        f.hash = (f.generate_hash(upload.path)
                  if waffle.switch_is_active('file-hash-paranoia')
                  else upload.hash)
        if upload.validation:
            validation = json.loads(upload.validation)
            if validation['metadata'].get('requires_chrome'):
                f.requires_chrome = True
        f.save()
        log.debug('New file: %r from %r' % (f, upload))
        # Move the uploaded file from the temp location.
        destinations = [version.path_prefix]
        if f.status in amo.MIRROR_STATUSES:
            destinations.append(version.mirror_path_prefix)
        for dest in destinations:
            copy_stored_file(upload.path,
                             os.path.join(dest, nfd_str(f.filename)))
        if upload.validation:
            FileValidation.from_json(f, upload.validation)
        return f

    @classmethod
    def get_jetpack_metadata(cls, path):
        data = {'sdkVersion': None, 'builderVersion': None}
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
                data['builderVersion'] = opts.get('builderVersion')
        return data

    def generate_hash(self, filename=None):
        """Generate a hash for a file."""
        hash = hashlib.sha256()
        with open(filename if filename else self.file_path, 'rb') as obj:
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
        if addon.is_webapp():
            extension = extension or '.webapp'
            parts.append(addon.app_slug)
            parts.append(self.version.version)
        else:
            extension = extension or '.xpi'
            name = slugify(addon.name).replace('-', '_') or 'addon'
            parts.append(name)
            parts.append(self.version.version)

            if self.version.compatible_apps:
                apps = '+'.join([a.shortername for a in
                                 self.version.compatible_apps])
                parts.append(apps)

            if self.platform_id and self.platform_id != amo.PLATFORM_ALL.id:
                parts.append(amo.PLATFORMS[self.platform_id].shortname)

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

    def latest_xpi_url(self):
        addon = self.version.addon
        kw = {'addon_id': addon.pk}
        if self.platform_id != amo.PLATFORM_ALL.id:
            kw['platform'] = self.platform_id
        if addon.is_premium() and addon.type != amo.ADDON_WEBAPP:
            url = reverse('downloads.watermarked', args=[self.id])
        else:
            url = reverse('downloads.latest', kwargs=kw)
        return os.path.join(url, 'addon-%s-latest%s' %
                            (addon.pk, self.extension))

    def eula_url(self):
        return reverse('addons.eula', args=[self.version.addon_id, self.id])

    @property
    def file_path(self):
        return os.path.join(settings.ADDONS_PATH, str(self.version.addon_id),
                            self.filename)

    @property
    def mirror_file_path(self):
        if self.version.addon.is_premium():
            return
        return os.path.join(settings.MIRROR_STAGE_PATH,
                            str(self.version.addon_id), self.filename)

    @property
    def guarded_file_path(self):
        return os.path.join(settings.GUARDED_ADDONS_PATH,
                            str(self.version.addon_id), self.filename)

    def watermarked_file_path(self, user_pk):
        return os.path.join(settings.WATERMARKED_ADDONS_PATH,
                            str(self.version.addon_id),
                            '%s-%s-%s' % (self.pk, user_pk, self.filename))

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

    @memoize(prefix='localepicker', time=0)
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

    def watermark_install_rdf(self, user):
        """
        Reads the install_rdf out of an addon and writes the user information
        into it.
        """
        inzip = SafeUnzip(self.file_path)
        inzip.is_valid()

        try:
            install = inzip.extract_path('install.rdf')
            data = RDF(install)
            data.set(user.email, self.version.addon.get_watermark_hash(user))
        except Exception, e:
            log.error('Could not alter install.rdf in file: %s for %s, %s'
                      % (self.pk, user.pk, e))
            raise

        return data

    def write_watermarked_addon(self, dest, data):
        """
        Writes the watermarked addon to the destination given
        the addons install.rdf data.
        """
        directory = os.path.dirname(dest)
        if not os.path.exists(directory):
            os.makedirs(directory)

        shutil.copyfile(self.file_path, dest)
        outzip = SafeUnzip(dest, mode='w')
        outzip.is_valid()
        outzip.zip.writestr('install.rdf', str(data))

    def watermark(self, user):
        """
        Creates a copy of the file and watermarks the
        metadata with the users.email. If something goes wrong, will
        raise an error, will return the dest if its ready to be served.
        """
        dest = self.watermarked_file_path(user.pk)

        with amo.utils.guard('marketplace.watermark.%s' % dest) as locked:
            if locked:
                # The calling method will need to do something about this.
                log.error('Watermarking collision: %s for %s' %
                          (self.pk, user.pk))
                return

            if os.path.exists(dest):
                age = time.time() - os.stat(dest)[stat.ST_ATIME]
                if age > settings.WATERMARK_REUSE_SECONDS:
                    log.debug('Removing stale watermark %s for %s %dsecs.' %
                             (self.pk, user.pk, age))
                    os.remove(dest)
                else:
                    log.debug('Reusing existing watermarked file: %s for %s' %
                             (self.pk, user.pk))
                    # Touch the update time so that the cron job won't delete
                    # us too quickly.
                    os.utime(dest, None)
                    return dest

            with statsd.timer('marketplace.watermark'):
                log.info('Starting watermarking of: %s for %s' %
                         (self.pk, user.pk))
                data = self.watermark_install_rdf(user)
                self.write_watermarked_addon(dest, data)

        return dest


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


@receiver(models.signals.post_delete, sender=File,
          dispatch_uid='version_update_status')
def update_status(sender, instance, **kw):
    if not kw.get('raw'):
        try:
            instance.version.addon.update_status(using='default')
        except models.ObjectDoesNotExist:
            pass


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


class Platform(amo.models.ModelBase):
    # `name` and `shortname` are provided in amo.__init__
    # name = TranslatedField()
    # shortname = TranslatedField()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'platforms'

    def __unicode__(self):
        if self.id in amo.PLATFORMS:
            return unicode(amo.PLATFORMS[self.id].name)
        else:
            log.warning('Invalid platform')
            return ''


class FileUpload(amo.models.ModelBase):
    """Created when a file is uploaded for validation/submission."""
    uuid = UUIDField(primary_key=True, auto=True)
    path = models.CharField(max_length=255, default='')
    name = models.CharField(max_length=255, default='',
                            help_text="The user's original filename")
    hash = models.CharField(max_length=255, default='')
    user = models.ForeignKey('users.UserProfile', null=True)
    valid = models.BooleanField(default=False)
    is_webapp = models.BooleanField(default=False)
    validation = models.TextField(null=True)
    compat_with_app = models.ForeignKey(Application, null=True,
                                    related_name='uploads_compat_for_app')
    compat_with_appver = models.ForeignKey(AppVersion, null=True,
                                    related_name='uploads_compat_for_appver')
    task_error = models.TextField(null=True)

    objects = amo.models.UncachedManagerBase()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'file_uploads'

    def __unicode__(self):
        return self.uuid

    def save(self, *args, **kw):
        if self.validation:
            try:
                if json.loads(self.validation)['errors'] == 0:
                    self.valid = True
            except Exception:
                log.error('Invalid validation json: %r' % self)
        super(FileUpload, self).save()

    def add_file(self, chunks, filename, size, is_webapp=False):
        filename = smart_str(filename)
        loc = os.path.join(settings.ADDONS_PATH, 'temp', uuid.uuid4().hex)
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
        self.is_webapp = is_webapp
        self.save()

    @classmethod
    def from_post(cls, chunks, filename, size, is_webapp=False):
        fu = FileUpload()
        fu.add_file(chunks, filename, size, is_webapp)
        return fu


class FileValidation(amo.models.ModelBase):
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
        js = json.loads(validation)
        new = cls(file=file, validation=validation, errors=js['errors'],
                  warnings=js['warnings'], notices=js['notices'])
        new.valid = new.errors == 0
        if ('metadata' in js and (
            js['metadata'].get('contains_binary_extension', False) or
            js['metadata'].get('contains_binary_content', False))):
            file.update(binary=True)
        if 'metadata' in js and js['metadata'].get('binary_components', False):
            file.update(binary_components=True)
        new.save()
        return new


def nfd_str(u):
    """Uses NFD to normalize unicode strings."""
    if isinstance(u, unicode):
        return unicodedata.normalize('NFD', u).encode('utf-8')
    return u


@django.dispatch.receiver(devhub.signals.submission_done)
def check_jetpack_version(sender, **kw):
    import files.tasks
    from files.utils import JetpackUpgrader

    minver, maxver = JetpackUpgrader().jetpack_versions()
    qs = File.objects.filter(version__addon=sender,
                             jetpack_version__isnull=False)
    ids = [f.id for f in qs
           if vint(minver) <= vint(f.jetpack_version) < vint(maxver)]
    if ids:
        files.tasks.start_upgrade.delay(ids, priority='high')
