from django.db import models

import amo
from versions.models import Version
from translations.fields import TranslatedField


class File(amo.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()

    version = models.ForeignKey(Version)
    platform = models.ForeignKey('Platform')
    filename = models.CharField(max_length=255, default='')
    size = models.PositiveIntegerField(default=0)
    hash = models.CharField(max_length=255, default='')
    codereview = models.BooleanField(default=False)
    status = models.PositiveSmallIntegerField(choices=STATUS_CHOICES,
                default=0)
    datestatuschanged = models.DateTimeField(null=True)

    class Meta(amo.ModelBase.Meta):
        db_table = 'files'


class Approval(amo.ModelBase):

    reviewtype = models.CharField(max_length=10, default='pending')
    action = models.IntegerField(default=0)
    os = models.CharField(max_length=255, default='')
    applications = models.CharField(max_length=255, default='')
    comments = models.TextField(null=True)

    addon = models.ForeignKey('addons.Addon')
    user = models.ForeignKey('users.UserProfile')
    file = models.ForeignKey(File)
    reply_to = models.ForeignKey('self', null=True, db_column='reply_to')

    class Meta(amo.ModelBase.Meta):
        db_table = 'approvals'


class Platform(amo.ModelBase):
    name = TranslatedField()
    shortname = TranslatedField()
    # icondata => mysql blob
    icontype = models.CharField(max_length=25, default='')

    class Meta(amo.ModelBase.Meta):
        db_table = 'platforms'


class TestCase(amo.ModelBase):
    test_group = models.ForeignKey('TestGroup')
    platform = models.ForeignKey('Platform')
    help_link = models.CharField(max_length=255, blank=True,
            help_text='Deprecated')
    function = models.CharField(max_length=255,
            help_text='Name of the function to call')

    class Meta(amo.ModelBase.Meta):
        db_table = 'test_cases'


class TestGroup(amo.ModelBase):
    category = models.CharField(max_length=255, blank=True)
    tier = models.PositiveSmallIntegerField(default=2,
            help_text="Run in order.  Tier 1 runs before Tier 2, etc.")
    critical = models.BooleanField(default=False,
            help_text="Should this group failing stop all tests?")
    types = models.PositiveIntegerField(default=0,
            help_text="Pretty sure it involves binary math... KHAN!!!")

    class Meta(amo.ModelBase.Meta):
        db_table = 'test_groups'


class TestResult(amo.ModelBase):
    file = models.ForeignKey(File)
    test_case = models.ForeignKey(TestCase)
    result = models.PositiveSmallIntegerField(default=0)
    line = models.PositiveIntegerField(default=0)
    filename = models.CharField(max_length=255, blank=True)
    message = models.TextField(blank=True)

    class Meta(amo.ModelBase.Meta):
        db_table = 'test_results'


class TestResultCache(amo.ModelBase):
    """When a file is checked the results are stored here in JSON.  This is
    temporary storage and removed with the garbage cleanup cron."""
    date = models.DateTimeField()
    key = models.CharField(max_length=255, db_index=True)
    test_case = models.ForeignKey(TestCase)
    message = models.TextField(blank=True)

    class Meta(amo.ModelBase.Meta):
        db_table = 'test_results_cache'
