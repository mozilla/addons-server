from datetime import date
import time

from django.conf import settings
from django.db import models

import amo.models
from amo.urlresolvers import reverse
from reviews.models import Review
from translations.fields import TranslatedField, translations_with_fallback


class AddonManager(amo.models.ManagerBase):

    def featured(self, app):
        """Get all the featured add-ons for an application in all locales."""
        qs = super(AddonManager, self).get_query_set()
        today = date.today()
        return qs.filter(feature__application=app.id,
                         feature__start__lte=today, feature__end__gte=today)


class Addon(amo.models.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()

    CONTRIBUTIONS_CHOICES = (
            (0, 'None'),
            (1, 'Passive; user shown message next to download button'),
            (2, 'User shown splash screen after download'),
            (3, 'Roadblock; User shown splash screen before download'),
    )

    guid = models.CharField(max_length=255, unique=True, null=True)
    name = TranslatedField()
    default_locale = models.CharField(max_length=10,
                                      default=settings.LANGUAGE_CODE,
                                      db_column='defaultlocale')

    type = models.ForeignKey('AddonType', db_column='addontype_id')
    status = models.PositiveIntegerField(
        choices=STATUS_CHOICES, db_index=True, default=0)
    highest_status = models.PositiveIntegerField(
        choices=STATUS_CHOICES, default=0,
        help_text="An upper limit for what an author can change.",
        db_column='higheststatus')
    icon_type = models.CharField(max_length=25, blank=True,
                                 db_column='icontype')
    homepage = TranslatedField()
    support_email = TranslatedField(db_column='supportemail')
    support_url = TranslatedField(db_column='supporturl')
    description = TranslatedField()

    summary = TranslatedField()
    developer_comments = TranslatedField(db_column='developercomments')
    eula = TranslatedField()
    privacy_policy = TranslatedField(db_column='privacypolicy')
    the_reason = TranslatedField()
    the_future = TranslatedField()

    average_rating = models.CharField(max_length=255, default=0,
                                      db_column='averagerating')
    bayesian_rating = models.FloatField(default=0, db_index=True,
                                        db_column='bayesianrating')
    total_reviews = models.PositiveIntegerField(default=0,
                                                db_column='totalreviews')
    weekly_downloads = models.PositiveIntegerField(
            default=0, db_column='weeklydownloads')
    total_downloads = models.PositiveIntegerField(
            default=0, db_column='totaldownloads')

    average_daily_downloads = models.PositiveIntegerField(default=0)
    average_daily_users = models.PositiveIntegerField(default=0)
    share_count = models.PositiveIntegerField(default=0, db_index=True,
                                              db_column='sharecount')

    inactive = models.BooleanField(default=False, db_index=True)
    trusted = models.BooleanField(default=False)
    view_source = models.BooleanField(default=False, db_column='viewsource')
    public_stats = models.BooleanField(default=False, db_column='publicstats')
    prerelease = models.BooleanField(default=False)
    admin_review = models.BooleanField(default=False, db_column='adminreview')
    site_specific = models.BooleanField(default=False,
                                        db_column='sitespecific')
    external_software = models.BooleanField(default=False,
                                            db_column='externalsoftware')
    binary = models.BooleanField(default=False,
                            help_text="Does the add-on contain a binary?")
    dev_agreement = models.BooleanField(default=False,
                            help_text="Has the dev agreement been signed?")
    wants_contributions = models.BooleanField(default=False)
    show_beta = models.BooleanField(default=True)

    nomination_date = models.DateTimeField(null=True,
                                           db_column='nominationdate')
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

    authors = models.ManyToManyField('users.UserProfile', through='AddonUser')

    objects = AddonManager()

    objects = AddonManager()

    class Meta:
        db_table = 'addons'

    def __unicode__(self):
        return '%s: %s' % (self.id, self.name)

    def get_absolute_url(self):
        return reverse('addons.detail', args=(self.id,))

    def fetch_translations(self, ids, lang):
        return translations_with_fallback(ids, lang, self.default_locale)

    def reviews(self):
        return Review.objects.filter(version__addon=self)

    def get_current_version(self):
        """
        Retrieves the latest public version of an addon.
        """
        try:
            return self.versions.filter(files__status=amo.STATUS_PUBLIC)[0]
        except IndexError:
            return None

    def get_icon_url(self):
        """
        Returns either the addon's icon url, or a default.
        """
        if not self.icon_type:
            if self.type_id == amo.ADDON_THEME:
                return settings.STATIC_URL + '/img/theme.png'
            else:
                return settings.STATIC_URL + '/img/default_icon.png'

        else:
            return settings.ADDON_ICON_URL % (
                    self.id, int(time.mktime(self.modified.timetuple())))

    def get_thumbnail_url(self):
        """
        Returns the addon's thumbnail url or a default.
        """
        try:
            preview = self.preview_set.order_by(
                    '-highlight', 'created').all()[0]
            return preview.get_thumbnail_url()

        except IndexError:
            return settings.STATIC_URL + '/img/no-preview.png'


class AddonCategory(models.Model):
    addon = models.ForeignKey(Addon)
    category = models.ForeignKey('Category')
    feature = models.BooleanField(default=False)
    feature_locales = models.CharField(max_length=255, default='')

    class Meta:
        db_table = 'addons_categories'


class AddonPledge(amo.models.ModelBase):
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


class AddonType(amo.models.ModelBase):
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


class BlacklistedGuid(amo.models.ModelBase):
    guid = models.CharField(max_length=255, unique=True)

    class Meta:
        db_table = 'blacklisted_guids'

    def __unicode__(self):
        return self.guid


class Category(amo.models.ModelBase):
    name = TranslatedField()
    slug = models.SlugField(max_length=50, help_text='Used in Category URLs.')
    description = TranslatedField()
    addontype = models.ForeignKey(AddonType)
    application = models.ForeignKey('applications.Application')
    count = models.IntegerField('Addon count')
    weight = models.IntegerField(
        help_text='Category weight used in sort ordering')

    addons = models.ManyToManyField(Addon, through='AddonCategory',
                                    related_name='categories')

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


class Feature(amo.models.ModelBase):
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


class Preview(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)
    filetype = models.CharField(max_length=25)
    thumbtype = models.CharField(max_length=25)
    caption = TranslatedField()
    highlight = models.BooleanField(default=False)

    class Meta:
        db_table = 'previews'

    def get_thumbnail_url(self):
        return (settings.PREVIEW_THUMBNAIL_URL %
                (str(self.id)[0], self.id,
                 int(time.mktime(self.modified.timetuple()))))
