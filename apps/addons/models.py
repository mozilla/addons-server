from datetime import datetime

from django.conf import settings
from django.contrib import admin
from django.db import models

import amo
from translations.fields import TranslatedField, translations_with_fallback


class Addon(amo.ModelBase):
    STATUS_CHOICES = (
            (0, 'Null'),
            (1, 'In the sandbox'),
            (2, 'Pending approval'),
            (3, 'Nominated to be public'),
            (4, 'Public'),
            (5, 'Disabled'),
            (6, 'Listed'),
            (7, 'Beta'),
            )

    CONTRIBUTIONS_CHOICES = (
            (0, 'None'),
            (1, 'Passive; user shown message next to download button'),
            (2, 'User shown splash screen after download'),
            (3, 'Roadblock; User shown splash screen before download'),
    )

    guid = models.CharField(max_length=255, unique=True)
    name = TranslatedField()
    defaultlocale = models.CharField(max_length=10,
                                     default=settings.LANGUAGE_CODE)

    addontype = models.ForeignKey('AddonType')
    status = models.PositiveIntegerField(choices=STATUS_CHOICES, db_index=True)
    higheststatus = models.PositiveIntegerField(choices=STATUS_CHOICES,
                    help_text="An upper limit for what an author can change.")
    icontype = models.CharField(max_length=25)
    homepage = TranslatedField()
    supportemail = TranslatedField()
    supporturl = TranslatedField()
    description = TranslatedField()
    summary = TranslatedField()
    developercomments = TranslatedField()
    eula = TranslatedField()
    privacypolicy = TranslatedField()
    the_reason = TranslatedField()
    the_future = TranslatedField()

    averagerating = models.CharField(max_length=255, default=0)
    bayesianrating = models.FloatField(default=0, db_index=True)
    totalreviews = models.PositiveIntegerField(default=0)
    weeklydownloads = models.PositiveIntegerField(default=0)
    totaldownloads = models.PositiveIntegerField(default=0)
    average_daily_downloads = models.PositiveIntegerField(default=0)
    average_daily_users = models.PositiveIntegerField(default=0)
    sharecount = models.PositiveIntegerField(default=0, db_index=True)

    inactive = models.BooleanField(default=False, db_index=True)
    trusted = models.BooleanField(default=False)
    viewsource = models.BooleanField(default=False)
    publicstats = models.BooleanField(default=False)
    prerelease = models.BooleanField(default=False)
    adminreview = models.BooleanField(default=False)
    sitespecific = models.BooleanField(default=False)
    externalsoftware = models.BooleanField(default=False)
    binary = models.BooleanField(default=False,
                            help_text="Does the add-on contain a binary?")
    dev_agreement = models.BooleanField(default=False,
                            help_text="Has the dev agreement been signed?")
    wants_contributions = models.BooleanField(default=False)
    show_beta = models.BooleanField(default=True)

    nominationdate = models.DateTimeField(null=True)
    target_locale = models.CharField(max_length=255, db_index=True, blank=True,
                            help_text="For dictionaries and language packs")
    locale_disambiguation = models.CharField(max_length=255, blank=True,
                            help_text="For dictionaries and language packs")

    paypal_id = models.CharField(max_length=255)
    suggested_amount = models.CharField(max_length=255,
                            help_text="Requested donation amount.")
    annoying = models.PositiveIntegerField(choices=STATUS_CHOICES, default=0)

    get_satisfaction_company = models.CharField(max_length=255)
    get_satisfaction_product = models.CharField(max_length=255)

    users = models.ManyToManyField('users.User')

    class Meta:
        db_table = 'addons'

    def get_absolute_url(self):
        # XXX: use reverse
        return '/addon/%s' % self.id

    def fetch_translations(self, ids, lang):
        return translations_with_fallback(ids, lang, self.defaultlocale)


class AddonType(amo.ModelBase):

    name = TranslatedField()
    name_plural = TranslatedField()
    description = TranslatedField()

    class Meta:
        db_table = 'addontypes'


class BlacklistedGuid(models.Model):

    guid = models.CharField(max_length=255, unique=True)
    created = models.DateTimeField(default=datetime.now, editable=False)

    class Meta:
        db_table = 'blacklisted_guids'

    def __unicode__(self):
        return self.guid


admin.site.register(BlacklistedGuid)
