import hashlib
import os
import uuid
import zipfile
import urlparse

from django.conf import settings
from django.db import models

import commonware
import path
from uuidfield.fields import UUIDField

import amo
import amo.models
import amo.utils
from amo.urlresolvers import reverse

log = commonware.log.getLogger('z.files')

# Acceptable extensions.
EXTENSIONS = ('.xpi', '.jar', '.xml')


class File(amo.models.ModelBase):
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

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'files'

    def __unicode__(self):
        return unicode(self.id)

    @property
    def amo_platform(self):
        # TODO: Ideally this would be ``platform``.
        return amo.PLATFORMS[self.platform_id]

    def get_url_path(self, src=None, release=False):
        if release:
            return urlparse.urljoin(settings.MIRROR_URL, '%s/%s' % (
                                    self.version.addon_id, self.filename))

        from amo.helpers import urlparams, absolutify
        url = os.path.join(reverse('downloads.file', args=[self.id]),
                           self.filename)
        # Firefox's Add-on Manager needs absolute urls.
        if src:
            return absolutify(urlparams(url, src=src))
        return absolutify(url)

    @classmethod
    def from_upload(cls, upload, version, platform):
        f = cls(version=version, platform=platform)
        upload.path = path.path(upload.path)
        f.filename = f.generate_filename(extension=upload.path.ext)
        f.size = upload.path.size
        f.jetpack = cls.is_jetpack(upload.path)
        # TODO: f.hash = upload.hash
        f.save()
        log.debug('New file: %r from %r' % (f, upload))
        # Detect addon-sdk-built addons.
        # Move the uploaded file from the temp location.
        dest = path.path(version.path_prefix)
        if not dest.exists():
            dest.makedirs()
        upload.path.rename(dest / f.filename)
        return f

    @classmethod
    def is_jetpack(cls, path):
        try:
            names = zipfile.ZipFile(path).namelist()
            return 'harness-options.json' in names
        except zipfile.BadZipfile:
            return False

    def generate_filename(self, extension='xpi'):
        """
        Files are in the format of:
        {addon_name}-{version}-{apps}-{platform}
        """
        parts = []
        parts.append(
                amo.utils.slugify(self.version.addon.name).replace('-', '_'))
        parts.append(self.version.version)

        if self.version.compatible_apps:
            apps = '+'.join([a.shortername for a in
                             self.version.compatible_apps])
            parts.append(apps)

        if self.platform_id and self.platform_id != amo.PLATFORM_ALL.id:
            parts.append(amo.PLATFORMS[self.platform_id].shortname)

        self.filename = '-'.join(parts) + '.' + extension
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
    def extension(self):
        return os.path.splitext(self.filename)[-1]


def cleanup_file(sender, instance, **kw):
    """ On delete of the file object from the database, unlink the file from
    the file system """
    try:
        filename = instance.file_path
    except models.ObjectDoesNotExist:
        return
    if os.path.exists(filename):
        os.remove(filename)

models.signals.post_delete.connect(cleanup_file,
            sender=File, dispatch_uid='cleanup_file')


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
    validation = models.TextField(null=True)
    task_error = models.TextField(null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'file_uploads'

    def __unicode__(self):
        return self.uuid

    @classmethod
    def from_post(cls, chunks, filename, size):
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
