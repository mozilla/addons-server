from django.conf import settings
from django.db import models

import amo
from translations.fields import TranslatedField, translations_with_fallback


class Addon(amo.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()

    CONTRIBUTIONS_CHOICES = (
            (0, 'None'),
            (1, 'Passive; user shown message next to download button'),
            (2, 'User shown splash screen after download'),
            (3, 'Roadblock; User shown splash screen before download'),
    )

    guid = models.CharField(max_length=255, unique=True, null=True)
    name = TranslatedField()
    defaultlocale = models.CharField(max_length=10,
                                     default=settings.LANGUAGE_CODE)

    addontype = models.ForeignKey('AddonType')
    status = models.PositiveIntegerField(
        choices=STATUS_CHOICES, db_index=True, default=0)
    higheststatus = models.PositiveIntegerField(
        choices=STATUS_CHOICES, default=0,
        help_text="An upper limit for what an author can change.")
    icontype = models.CharField(max_length=25, blank=True)
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

    paypal_id = models.CharField(max_length=255, blank=True)
    suggested_amount = models.CharField(max_length=255, blank=True,
                            help_text="Requested donation amount.")
    annoying = models.PositiveIntegerField(choices=CONTRIBUTIONS_CHOICES,
                                           default=0)

    get_satisfaction_company = models.CharField(max_length=255, blank=True)
    get_satisfaction_product = models.CharField(max_length=255, blank=True)

    users = models.ManyToManyField('users.UserProfile', through='AddonUser')

    class Meta:
        db_table = 'addons'

    def __unicode__(self):
        return '%s: %s' % (self.id, self.name)

    def get_absolute_url(self):
        # XXX: use reverse
        return '/addon/%s' % self.id

    def fetch_translations(self, ids, lang):
        return translations_with_fallback(ids, lang, self.defaultlocale)


class AddonCategory(models.Model):
    addon = models.ForeignKey(Addon)
    category = models.ForeignKey('Category')
    feature = models.BooleanField(default=False)
    feature_locales = models.CharField(max_length=255, default='')

    class Meta:
        db_table = 'addons_categories'


class AddonPledge(amo.ModelBase):
    addon = models.ForeignKey(Addon)
    target = models.PositiveIntegerField() # Only $ for now
    what_ima_gonna_do = TranslatedField()
    active = models.BooleanField(default=False)
    deadline = models.DateField(null=True)

    class Meta:
        db_table = 'addons_pledges'

    def __unicode__(self):
        return '%s ($%s, %s)' % (self.addon.name, self.target, self.deadline)


class AddonRecommendation(models.Model):
    addon = models.ForeignKey(Addon, related_name="addon_one")
    other_addon = models.ForeignKey(Addon, related_name="addon_two")
    score = models.FloatField()

    class Meta:
        db_table = 'addon_recommendations'


class AddonType(amo.ModelBase):
    name = TranslatedField()
    name_plural = TranslatedField()
    description = TranslatedField()

    class Meta:
        db_table = 'addontypes'

    def __unicode__(self):
        return unicode(self.name)


class AddonUser(models.Model):
    AUTHOR_CHOICES = amo.AUTHOR_CHOICES.items()

    addon = models.ForeignKey(Addon)
    user = models.ForeignKey('users.UserProfile')
    role = models.SmallIntegerField(default=5, choices=AUTHOR_CHOICES)
    listed = models.BooleanField(default=True)
    position = models.IntegerField(default=0)

    class Meta:
        db_table = 'addons_users'


class BlacklistedGuid(amo.ModelBase):
    guid = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'blacklisted_guids'

    def __unicode__(self):
        return self.guid


class Category(amo.ModelBase):
    name = TranslatedField()
    description = TranslatedField()
    addontype = models.ForeignKey(AddonType)
    application = models.ForeignKey('applications.Application')
    count = models.IntegerField('Addon count')
    weight = models.IntegerField(
        help_text='Category weight used in sort ordering')

    addons = models.ManyToManyField(Addon, through='AddonCategory')

    class Meta:
        db_table = 'categories'
        verbose_name_plural = 'Categories'

    def __unicode__(self):
        return unicode(self.name)


class CompatibilityReport(models.Model):
    guid = models.CharField(max_length=128, db_index=True)
    works_properly = models.NullBooleanField()
    app_guid = models.CharField(max_length=128, blank=True)
    app_version = models.CharField(max_length=128, blank=True)
    app_build = models.CharField(max_length=128, blank=True)
    client_os = models.CharField(max_length=128, blank=True)
    client_ip = models.CharField(max_length=128, blank=True)
    version = models.CharField(max_length=128, default='0.0')
    comments = models.TextField()
    other_addons = models.TextField()
    created = models.DateTimeField(null=True)

    class Meta:
        db_table = 'compatibility_reports'


class Feature(amo.ModelBase):
    addon = models.ForeignKey(Addon)
    start = models.DateTimeField()
    end = models.DateTimeField()
    locale = models.CharField(max_length=10, default='', blank=True)
    application = models.ForeignKey('applications.Application')

    class Meta:
        db_table = 'features'

    def __unicode__(self):
        return '%s (%s: %s)' % (self.addon.name, self.application.name,
                                self.locale)


class Preview(amo.ModelBase):
    addon = models.ForeignKey(Addon)
    filetype = models.CharField(max_length=25)
    thumbtype = models.CharField(max_length=25)
    caption = TranslatedField()
    highlight = models.BooleanField(default=False)

    class Meta:
        db_table = 'previews'
