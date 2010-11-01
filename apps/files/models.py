import os

from django.conf import settings
from django.db import models

from uuidfield.fields import UUIDField

import amo.models
import amo.utils
from amo.urlresolvers import reverse


class File(amo.models.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()

    version = models.ForeignKey('versions.Version', related_name='files')
    platform = models.ForeignKey('Platform')
    filename = models.CharField(max_length=255, default='')
    size = models.PositiveIntegerField(default=0)  # kilobytes
    hash = models.CharField(max_length=255, default='')
    codereview = models.BooleanField(default=False)
    jetpack = models.BooleanField(default=False)
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES,
                default=0)
    datestatuschanged = models.DateTimeField(null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'files'

    @property
    def amo_platform(self):
        # TODO: Ideally this would be ``platform``.
        return amo.PLATFORMS[self.platform_id]

    def get_url_path(self, app, src):
        # TODO: remove app
        from amo.helpers import urlparams
        url = reverse('downloads.file', args=[self.id]) + self.filename
        return urlparams(url, src=src)

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
    filename = instance.file_path
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
        return unicode(amo.PLATFORMS[self.id].name)


class FileUpload(amo.models.ModelBase):
    """Created when a file is uploaded for validation/submission."""
    uuid = UUIDField(primary_key=True, auto=True)
    path = models.CharField(max_length=255)
    name = models.CharField(max_length=255,
                            help_text="The user's original filename")
    user = models.ForeignKey('users.UserProfile', null=True)
    validation = models.TextField(null=True)
    task_error = models.TextField(null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'file_uploads'


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
