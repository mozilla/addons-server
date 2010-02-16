from datetime import date
import time

from django.conf import settings
from django.db import models
from django.db.models import Q

import amo.models
from amo.urlresolvers import reverse
from reviews.models import Review
from translations.fields import TranslatedField, translations_with_fallback
from users.models import UserProfile


class AddonManager(amo.models.ManagerBase):

    def public(self):
        """Get public add-ons only"""
        return self.filter(inactive=False, status=amo.STATUS_PUBLIC)

    def experimental(self):
        """Get only experimental add-ons"""
        return self.filter(inactive=False, status__in=EXPERIMENTAL_STATUSES)

    def valid(self):
        """Get valid, enabled add-ons only"""
        return self.filter(status__in=amo.VALID_STATUSES, inactive=False)

    def featured(self, app):
        """Filter for all featured add-ons for an application in all locales."""
        today = date.today()
        return self.filter(feature__application=app.id,
                           feature__start__lte=today, feature__end__gte=today)

    def category_featured(self):
        """Get all category-featured add-ons for ``app`` in all locales."""
        return self.filter(addoncategory__feature=True)

    def listed(self, app, *status):
        """
        Listed add-ons have a version with a file matching ``status`` and are
        not inactive.  TODO: handle personas and listed add-ons.
        """
        if len(status) == 0:
            status = [amo.STATUS_PUBLIC]

        # XXX: handle personas (no versions) and listed (no files)
        return self.filter(inactive=False, status__in=status,
                           versions__applicationsversions__application=app.id,
                           versions__files__status__in=status)


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
    target_locale = models.CharField(
        max_length=255, db_index=True, blank=True, null=True,
        help_text="For dictionaries and language packs")
    locale_disambiguation = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="For dictionaries and language packs")

    paypal_id = models.CharField(max_length=255, blank=True)
    suggested_amount = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="Requested donation amount.")
    annoying = models.PositiveIntegerField(choices=CONTRIBUTIONS_CHOICES,
                                           default=0)

    get_satisfaction_company = models.CharField(max_length=255, blank=True,
                                               null=True)
    get_satisfaction_product = models.CharField(max_length=255, blank=True,
                                               null=True)

    authors = models.ManyToManyField('users.UserProfile', through='AddonUser',
                                     related_name='addons')

    objects = AddonManager()

    class Meta:
        db_table = 'addons'

    def __unicode__(self):
        return '%s: %s' % (self.id, self.name)

    def get_absolute_url(self):
        return reverse('addons.detail', args=(self.id,))

    @classmethod
    def get_fallback(cls):
        return cls._meta.get_field('default_locale')

    @property
    def listed_authors(self):
        return UserProfile.objects.filter(
            addons=self, addonuser__listed=True).order_by('addonuser__position')

    def fetch_translations(self, ids, lang):
        return translations_with_fallback(ids, lang, self.default_locale)

    @property
    def reviews(self):
        return Review.objects.filter(version__addon=self)

    @amo.cached_property
    def current_version(self):
        """Retrieves the latest listed version of an addon."""
        try:
            if self.status == amo.STATUS_PUBLIC:
                status = [self.status]
            else:
                status = amo.VALID_STATUSES
            return self.versions.filter(files__status__in=status)[0]
        except IndexError:
            return None

    @property
    def icon_url(self):
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

    @property
    def thumbnail_url(self):
        """
        Returns the addon's thumbnail url or a default.
        """
        try:
            preview = self.preview_set.order_by(
                    '-highlight', 'created').all()[0]
            return preview.get_thumbnail_url()

        except IndexError:
            return settings.STATIC_URL + '/img/no-preview.png'

    def is_experimental(self):
        return self.status in amo.EXPERIMENTAL_STATUSES

    def is_featured(self, app, lang):
        """is add-on globally featured for this app and language?"""
        locale_filter = (Q(feature__locale=lang) |
                         Q(feature__locale__isnull=True) |
                         Q(feature__locale=''))
        feature = Addon.objects.featured(app).filter(
            locale_filter, pk=self.pk)[:1]
        return bool(feature)

    def is_category_featured(self, app, lang):
        """is add-on featured in any category for this app?"""
        # XXX should probably take feature_locales under consideration, even
        # though remora didn't do that
        feature = AddonCategory.objects.filter(
            addon=self, feature=True, category__application__id=app.id).count()
        return bool(feature)

    @amo.cached_property
    def compatible_apps(self):
        """Shortcut to get compatible apps for the current version."""
        if self.current_version:
            return self.current_version.compatible_apps
        else:
            return {}


class AddonCategory(models.Model):
    addon = models.ForeignKey(Addon)
    category = models.ForeignKey('Category')
    feature = models.BooleanField(default=False)
    feature_locales = models.CharField(max_length=255, default='', null=True)

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
    role = models.SmallIntegerField(default=amo.AUTHOR_ROLE_OWNER,
                                    choices=AUTHOR_CHOICES)
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
    type = models.ForeignKey('AddonType', db_column='addontype_id')
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
    locale = models.CharField(max_length=10, default='', blank=True, null=True)
    application = models.ForeignKey('applications.Application')

    class Meta:
        db_table = 'features'

    def __unicode__(self):
        app = amo.APP_IDS[self.application.id].pretty
        return '%s (%s: %s)' % (self.addon.name, app, self.locale)


class Preview(amo.models.ModelBase):
    addon = models.ForeignKey(Addon)
    filetype = models.CharField(max_length=25)
    thumbtype = models.CharField(max_length=25)
    caption = TranslatedField()
    highlight = models.BooleanField(default=False)

    class Meta:
        db_table = 'previews'

    def get_thumbnail_url(self):
        if self.modified is not None:
            modified = int(time.mktime(self.modified.timetuple()))
        else:
            modified = 0
        return (settings.PREVIEW_THUMBNAIL_URL %
                (self.id / 1000, self.id, modified))
