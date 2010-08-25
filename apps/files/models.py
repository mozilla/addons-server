import os

from django.conf import settings
from django.db import models
from django.utils import translation

import amo.models
from amo.urlresolvers import reverse
from cake.urlresolvers import remora_url


class File(amo.models.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()

    version = models.ForeignKey('versions.Version', related_name='files')
    platform = models.ForeignKey('Platform')
    filename = models.CharField(max_length=255, default='')
    size = models.PositiveIntegerField(default=0)
    hash = models.CharField(max_length=255, default='')
    codereview = models.BooleanField(default=False)
    jetpack = models.BooleanField(default=False)
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES,
                default=0)
    datestatuschanged = models.DateTimeField(null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'files'

    def get_url_path(self, app, src):
        from amo.helpers import urlparams
        lang = translation.get_language()
        base = settings.FILES_URL % (lang, app.short, self.id,
                                     self.filename, src)
        return urlparams(base, confirmed=1)

    def latest_xpi_url(self):
        # TODO(jbalogh): reverse?
        addon = self.version.addon_id
        url = ['/downloads/latest/%s' % addon]
        if self.platform_id != amo.PLATFORM_ALL.id:
            url.append('platform:%s' % self.platform_id)
        url.append('addon-%s-latest%s' % (addon, self.extension))
        return remora_url(os.path.join(*url))

    def eula_url(self):
        return reverse('addons.eula', args=[self.version.addon_id, self.id])

    @property
    def extension(self):
        return os.path.splitext(self.filename)[-1]


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
