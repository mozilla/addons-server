from datetime import datetime, timedelta
import hashlib
import json
import os
import posixpath
import uuid
import shutil
import zipfile

from django.conf import settings
from django.db import models
from django.template.defaultfilters import slugify
from django.utils.encoding import smart_str

import commonware
import path
from uuidfield.fields import UUIDField

import amo
import amo.models
import amo.utils
from amo.urlresolvers import reverse
from files.utils import nfd_str

log = commonware.log.getLogger('z.files')

# Acceptable extensions.
EXTENSIONS = ('.xpi', '.jar', '.xml')


class File(amo.models.OnChangeMixin, amo.models.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()

    version = models.ForeignKey('versions.Version', related_name='files')
    platform = models.ForeignKey('Platform', default=amo.PLATFORM_ALL.id)
    filename = models.CharField(max_length=255, default='')
    size = models.PositiveIntegerField(default=0)  # kilobytes
    hash = models.CharField(max_length=255, default='')
    # TODO: delete this column
    codereview = models.BooleanField(default=False)
    jetpack = models.BooleanField(default=False)
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES,
                                              default=amo.STATUS_UNREVIEWED)
    datestatuschanged = models.DateTimeField(null=True, auto_now_add=True)
    no_restart = models.BooleanField(default=False)

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

    def get_mirror(self, addon, attachment=False):
        if self.datestatuschanged:
            published = datetime.now() - self.datestatuschanged
        else:
            published = timedelta(minutes=0)

        # This is based on the logic of what gets copied to the mirror
        # at: http://bit.ly/h5qm4o
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

    def get_url_path(self, app, src):
        # TODO: remove app
        from amo.helpers import urlparams, absolutify
        url = os.path.join(reverse('downloads.file', args=[self.id]),
                           self.filename)
        # Firefox's Add-on Manager needs absolute urls.
        return absolutify(urlparams(url, src=src))

    @classmethod
    def from_upload(cls, upload, version, platform, parse_data={}):
        f = cls(version=version, platform=platform)
        upload.path = path.path(nfd_str(upload.path))
        f.filename = f.generate_filename(extension=upload.path.ext)
        f.size = int(max(1, round(upload.path.size / 1024, 0)))  # Kilobytes.
        f.jetpack = cls.is_jetpack(upload.path)
        f.hash = upload.hash
        f.no_restart = parse_data.get('no_restart', False)
        if version.addon.status == amo.STATUS_PUBLIC:
            if amo.VERSION_BETA.search(parse_data.get('version', '')):
                f.status = amo.STATUS_BETA
            elif version.addon.trusted:
                f.status = amo.STATUS_PUBLIC
        f.save()
        log.debug('New file: %r from %r' % (f, upload))
        # Move the uploaded file from the temp location.
        destinations = [path.path(version.path_prefix)]
        if f.status in amo.MIRROR_STATUSES:
            destinations.append(path.path(version.mirror_path_prefix))
        for dest in destinations:
            if not dest.exists():
                dest.makedirs()
            upload.path.copyfile(dest / nfd_str(f.filename))
        FileValidation.from_json(f, upload.validation)
        return f

    @classmethod
    def is_jetpack(cls, path):
        try:
            names = zipfile.ZipFile(path).namelist()
            return 'harness-options.json' in names
        except zipfile.BadZipfile:
            return False

    def generate_filename(self, extension='.xpi'):
        """
        Files are in the format of:
        {addon_name}-{version}-{apps}-{platform}
        """
        parts = []
        # slugify drops unicode so we may end up with an empty string.
        # Apache did not like serving unicode filenames (bug 626587).
        name = slugify(self.version.addon.name).replace('-', '_') or 'addon'
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

    def latest_xpi_url(self):
        addon = self.version.addon_id
        kw = {'addon_id': addon}
        if self.platform_id != amo.PLATFORM_ALL.id:
            kw['platform'] = self.platform_id
        url = reverse('downloads.latest', kwargs=kw)
        return os.path.join(url, 'addon-%s-latest%s' % (addon, self.extension))

    def eula_url(self):
        return reverse('addons.eula', args=[self.version.addon_id, self.id])

    @property
    def file_path(self):
        return os.path.join(settings.ADDONS_PATH, str(self.version.addon_id),
                            self.filename)

    @property
    def mirror_file_path(self):
        return os.path.join(settings.MIRROR_STAGE_PATH,
                            str(self.version.addon_id), self.filename)

    @property
    def guarded_file_path(self):
        return os.path.join(settings.GUARDED_ADDONS_PATH,
                            str(self.version.addon_id), self.filename)

    @property
    def extension(self):
        return os.path.splitext(self.filename)[-1]

    @classmethod
    def mv(cls, src, dst):
        """Move a file from src to dst."""
        try:
            src, dst = path.path(src), path.path(dst)
            if src.exists():
                if not dst.dirname().exists():
                    dst.dirname().makedirs()
                src.rename(dst)
        except UnicodeEncodeError:
            log.error('Move Failure: %s %s' % (smart_str(src), smart_str(dst)))

    def hide_disabled_file(self):
        """Move a disabled file to the guarded file path."""
        if not self.filename:
            return
        src, dst = self.file_path, self.guarded_file_path
        if os.path.exists(src):
            log.info('Moving disabled file: %s => %s' % (src, dst))
            self.mv(src, dst)
        # Remove the file from the mirrors if necessary.
        if os.path.exists(self.mirror_file_path):
            log.info('Unmirroring disabled file: %s'
                     % self.mirror_file_path)
            os.remove(self.mirror_file_path)

    def unhide_disabled_file(self):
        if not self.filename:
            return
        src, dst = self.guarded_file_path, self.file_path
        if os.path.exists(src):
            log.info('Moving undisabled file: %s => %s' % (src, dst))
            self.mv(src, dst)

    def copy_to_mirror(self):
        if not self.filename:
            return
        try:
            if os.path.exists(self.file_path):
                dst = self.mirror_file_path
                log.info('Moving file to mirror: %s => %s'
                         % (self.file_path, dst))
                if not os.path.exists(os.path.dirname(dst)):
                    os.makedirs(os.path.dirname(dst))
                shutil.copyfile(self.file_path, dst)
        except UnicodeEncodeError:
            log.info('Copy Failure: %s %s %s' %
                     (self.id, smart_str(self.filename),
                      smart_str(self.file_path)))


def update_status(sender, instance, **kw):
    if not kw.get('raw'):
        try:
            instance.version.addon.update_status(using='default')
        except models.ObjectDoesNotExist:
            pass

models.signals.post_delete.connect(update_status, sender=File,
                                   dispatch_uid='version_update_status')


def cleanup_file(sender, instance, **kw):
    """ On delete of the file object from the database, unlink the file from
    the file system """
    if kw.get('raw') or not instance.filename:
        return
    # Use getattr so the paths are accessed inside the try block.
    for path in ('file_path', 'mirror_file_path'):
        try:
            filename = getattr(instance, path)
        except models.ObjectDoesNotExist:
            return
        if os.path.exists(filename):
            os.remove(filename)

models.signals.post_delete.connect(cleanup_file, sender=File,
                                   dispatch_uid='cleanup_file')


@File.on_change
def check_file_status(old_attr, new_attr, instance, sender, **kw):
    if kw.get('raw'):
        return
    old, new = old_attr.get('status'), instance.status
    if new == amo.STATUS_DISABLED and old != amo.STATUS_DISABLED:
        instance.hide_disabled_file()
    elif old == amo.STATUS_DISABLED and new != amo.STATUS_DISABLED:
        instance.unhide_disabled_file()


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

    @staticmethod
    def total_reviews():
        return (Approval.objects.values('user', 'user__display_name')
                                .annotate(approval_count=models.Count('id'))
                                .order_by('-approval_count')[:5])

    @staticmethod
    def monthly_reviews():
        now = datetime.now()
        created_date = datetime(now.year, now.month, 1)
        return (Approval.objects.values('user', 'user__display_name')
                                .filter(created__gte=created_date)
                                .annotate(approval_count=models.Count('id'))
                                .order_by('-approval_count')[:5])


class Platform(amo.models.ModelBase):
    # `name` and `shortname` are provided in amo.__init__
    # name = TranslatedField()
    # shortname = TranslatedField()
    # icondata => mysql blob
    icontype = models.CharField(max_length=25, default='')

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
    path = models.CharField(max_length=255)
    name = models.CharField(max_length=255,
                            help_text="The user's original filename")
    hash = models.CharField(max_length=255, default='')
    user = models.ForeignKey('users.UserProfile', null=True)
    valid = models.BooleanField(default=False)
    validation = models.TextField(null=True)
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

    @classmethod
    def from_post(cls, chunks, filename, size):
        filename = smart_str(filename)
        loc = path.path(settings.ADDONS_PATH) / 'temp' / uuid.uuid4().hex
        if not loc.dirname().exists():
            loc.dirname().makedirs()
        ext = path.path(filename).ext
        if ext in EXTENSIONS:
            loc += ext
        log.info('UPLOAD: %r (%s bytes) to %r' % (filename, size, loc))
        hash = hashlib.sha256()
        with open(loc, 'wb') as fd:
            for chunk in chunks:
                hash.update(chunk)
                fd.write(chunk)
        return cls.objects.create(path=loc, name=filename,
                                  hash='sha256:%s' % hash.hexdigest())


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
        new.save()
        return new


class TestCase(amo.models.ModelBase):
    test_group = models.ForeignKey('TestGroup')
    help_link = models.CharField(max_length=255, blank=True,
            help_text='Deprecated')
    function = models.CharField(max_length=255,
            help_text='Name of the function to call')

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'test_cases'


class TestGroup(amo.models.ModelBase):
    category = models.CharField(max_length=255, blank=True)
    tier = models.PositiveSmallIntegerField(default=2,
            help_text="Run in order.  Tier 1 runs before Tier 2, etc.")
    critical = models.BooleanField(default=False,
            help_text="Should this group failing stop all tests?")
    types = models.PositiveIntegerField(default=0,
            help_text="Pretty sure it involves binary math... KHAN!!!")

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'test_groups'


class TestResult(amo.models.ModelBase):
    file = models.ForeignKey(File)
    test_case = models.ForeignKey(TestCase)
    result = models.PositiveSmallIntegerField(default=0)
    line = models.PositiveIntegerField(default=0)
    filename = models.CharField(max_length=255, blank=True)
    message = models.TextField(blank=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'test_results'


class TestResultCache(models.Model):
    """When a file is checked the results are stored here in JSON.  This is
    temporary storage and removed with the garbage cleanup cron."""
    date = models.DateTimeField()
    key = models.CharField(max_length=255, db_index=True)
    test_case = models.ForeignKey(TestCase)
    value = models.TextField(blank=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'test_results_cache'
