from datetime import date
import time

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum

import caching.base

import amo.models
from amo.fields import DecimalCharField
from amo.urlresolvers import reverse
from reviews.models import Review
from translations.fields import (TranslatedField, PurifiedField,
                                 LinkifiedField, translations_with_fallback)
from users.models import UserProfile
from search import utils as search_utils
from stats.models import Contribution as ContributionStats


class AddonManager(amo.models.ManagerBase):

    def public(self):
        """Get public add-ons only"""
        return self.filter(inactive=False, status=amo.STATUS_PUBLIC)

    def experimental(self):
        """Get only experimental add-ons"""
        return self.filter(inactive=False,
                           status__in=amo.EXPERIMENTAL_STATUSES)

    def valid(self):
        """Get valid, enabled add-ons only"""
        return self.filter(status__in=amo.VALID_STATUSES, inactive=False)

    def featured(self, app):
        """
        Filter for all featured add-ons for an application in all locales.
        """
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
                           versions__files__status__in=status).distinct()

    def compatible_with_app(self, app, version=None):
        """
        Returns addons compatible with specific applcications and optionally
        specific versions of said application.

        E.g. amo.FIREFOX and '3.5'
        """
        qs = self.filter(
                versions__applicationsversions__min__application=app.id)

        if version is not None:

            version_int = search_utils.convert_version(version)
            qs = qs.filter(
                versions__applicationsversions__min__version_int__lte=
                version_int,
                versions__applicationsversions__max__version_int__gte=
                version_int).distinct()

        return qs.distinct()

    def compatible_with_platform(self, platform):
        """
        `platform` can be either a class amo.PLATFORM_* or an id
        """

        if isinstance(platform, int):
            platform = amo.PLATFORMS.get(id, amo.PLATFORM_ALL)

        if platform not in amo.PLATFORMS:
            platform = amo.PLATFORM_DICT.get(platform, amo.PLATFORM_ALL)

        if platform != amo.PLATFORM_ALL:
            return (self.filter(
                    Q(versions__files__platform=platform.id) |
                    Q(versions__files__platform=amo.PLATFORM_ALL.id))
                    .distinct())

        return self.distinct()


class Addon(amo.models.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()
    CONTRIB_CHOICES = sorted(amo.CONTRIB_CHOICES.items())

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
    description = PurifiedField()

    summary = LinkifiedField()
    developer_comments = PurifiedField(db_column='developercomments')
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
    last_updated = models.DateTimeField(db_index=True, null=True,
        help_text='Last time this add-on had a file/version update')

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
    # TODO(jbalogh): remove nullify_invalid once remora dies.
    suggested_amount = DecimalCharField(max_digits=8, decimal_places=2,
                                        nullify_invalid=True,
                                        blank=True, null=True,
                                        help_text="Requested donation amount.")
    annoying = models.PositiveIntegerField(choices=CONTRIB_CHOICES, default=0)
    enable_thankyou = models.BooleanField(default=False,
        help_text="Should the thankyou note be sent to contributors?")
    thankyou_note = TranslatedField()

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

    def get_url_path(self):
        return reverse('addons.detail', args=(self.id,))

    def meet_the_dev_url(self, extra=None):
        args = [self.id, extra] if extra else [self.id]
        return reverse('addons.meet', args=args)

    @property
    def reviews_url(self):
        return reverse('reviews.list', args=(self.id,))

    @property
    def listed_authors(self):
        return UserProfile.objects.filter(addons=self,
                addonuser__listed=True).order_by('addonuser__position')

    @classmethod
    def get_fallback(cls):
        return cls._meta.get_field('default_locale')

    def fetch_translations(self, ids, lang):
        return translations_with_fallback(ids, lang, self.default_locale)

    @property
    def reviews(self):
        return Review.objects.filter(version__addon=self)

    @amo.cached_property
    def current_version(self):
        """Retrieves the latest version of an addon."""
        try:
            if self.status == amo.STATUS_PUBLIC:
                status = [self.status]
            elif self.status == amo.STATUS_LISTED:
                return self.versions.get()
            else:
                status = amo.VALID_STATUSES
            return self.versions.filter(files__status__in=status)[0]
        except IndexError:
            return None

    @amo.cached_property
    def current_beta_version(self):
        """Retrieves the latest version of an addon, in the beta channel."""
        versions = self.versions.filter(files__status=amo.STATUS_BETA)

        if len(versions):
            return versions[0]

    @property
    def icon_url(self):
        """
        Returns either the addon's icon url, or a default.
        """
        if not self.icon_type:
            if self.type_id == amo.ADDON_THEME:
                icon = 'default-theme.png'
            else:
                icon = 'default-addon.png'
            return settings.MEDIA_URL + 'img/amo2009/icons/' + icon

        else:
            return settings.ADDON_ICON_URL % (
                    self.id, int(time.mktime(self.modified.timetuple())))

    @property
    def contribution_url(self, lang=settings.LANGUAGE_CODE,
                         app=settings.DEFAULT_APP):
        return '/%s/%s/addons/contribute/%d' % (lang, app, self.id)

    @amo.cached_property
    def preview_count(self):
        return self.previews.all().count()

    @property
    def thumbnail_url(self):
        """
        Returns the addon's thumbnail url or a default.
        """
        try:
            preview = self.previews.all()[0]
            return preview.thumbnail_url

        except IndexError:
            return settings.MEDIA_URL + '/img/amo2009/icons/no-preview.png'

    @property
    def is_listed(self):
        return self.status == amo.STATUS_LISTED

    def is_unreviewed(self):
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
            addon=self, feature=True, category__application__id=app.id)
        return bool(feature[:1])

    @amo.cached_property
    def compatible_apps(self):
        """Shortcut to get compatible apps for the current version."""
        if self.current_version:
            return self.current_version.compatible_apps
        else:
            return {}

    def has_author(self, user, roles=None):
        """True if ``user`` is an author with any of the specified ``roles``.

        ``roles`` should be a list of valid roles (see amo.AUTHOR_ROLE_*). If
        not specified, then has_author will return true if the user has any
        role other than amo.AUTHOR_ROLE_NONE.
        """
        if user is None:
            return False
        if roles is None:
            roles = amo.AUTHOR_CHOICES.keys()
            roles.remove(amo.AUTHOR_ROLE_NONE)
        return bool(AddonUser.objects.filter(addon=self, user=user,
                                             role__in=roles))

    @property
    def takes_contributions(self):
        # TODO(jbalogh): config.paypal_disabled
        return self.wants_contributions and self.paypal_id

    @property
    def has_eula(self):
        return self.eula and self.eula.localized_string


class AddonCategory(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey(Addon)
    category = models.ForeignKey('Category')
    feature = models.BooleanField(default=False)
    feature_locales = models.CharField(max_length=255, default='', null=True)

    objects = caching.base.CachingManager()

    class Meta:
        db_table = 'addons_categories'
        unique_together = ('addon', 'category')


class PledgeManager(amo.models.ManagerBase):

    def ongoing(self):
        """Get non-expired pledges only"""
        return self.filter(deadline__gte=date.today())


class AddonPledge(amo.models.ModelBase):
    addon = models.ForeignKey(Addon, related_name='pledges')
    target = models.PositiveIntegerField()  # Only $ for now
    what_ima_gonna_do = TranslatedField()
    active = models.BooleanField(default=False)
    deadline = models.DateField(null=True)

    objects = PledgeManager()

    class Meta:
        db_table = 'addons_pledges'
        ordering = ('-deadline',)

    @property
    def contributions(self):
        return ContributionStats.objects.filter(
            addon=self.addon, created__gte=self.created,
            created__lte=self.deadline, transaction_id__isnull=False)

    @amo.cached_property
    def num_users(self):
        return self.contributions.count()

    @amo.cached_property
    def raised(self):
        qs = self.contributions.aggregate(raised=Sum('amount'))
        return qs['raised']

    def __unicode__(self):
        return '%s ($%s, %s)' % (self.addon.name, self.target, self.deadline)


class AddonRecommendation(models.Model):
    """
    Add-on recommendations. For each `addon`, a group of `other_addon`s
    is recommended with a score (= correlation coefficient).
    """
    addon = models.ForeignKey(Addon, related_name="addon_recommendations")
    other_addon = models.ForeignKey(Addon, related_name="recommended_for")
    score = models.FloatField()

    class Meta:
        db_table = 'addon_recommendations'
        ordering = ('-score',)


class AddonType(amo.models.ModelBase):
    name = TranslatedField()
    name_plural = TranslatedField()
    description = TranslatedField()

    class Meta:
        db_table = 'addontypes'

    def __unicode__(self):
        return unicode(self.name)


class AddonUser(caching.base.CachingMixin, models.Model):
    AUTHOR_CHOICES = amo.AUTHOR_CHOICES.items()

    addon = models.ForeignKey(Addon)
    user = models.ForeignKey('users.UserProfile')
    role = models.SmallIntegerField(default=amo.AUTHOR_ROLE_OWNER,
                                    choices=AUTHOR_CHOICES)
    listed = models.BooleanField(default=True)
    position = models.IntegerField(default=0)

    objects = caching.base.CachingManager()

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

    def get_url_path(self):
        # TODO(jbalogh): reverse the real urls
        base = reverse('home')
        return '%sbrowse/type:%s/cat:%s' % (base, self.type_id, self.id)


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
    addon = models.ForeignKey(Addon, related_name='previews')
    filetype = models.CharField(max_length=25)
    thumbtype = models.CharField(max_length=25)
    caption = TranslatedField()
    highlight = models.BooleanField(default=False)

    class Meta:
        db_table = 'previews'
        ordering = ('-highlight', 'created')

    def _image_url(self, thumb=True):
        if self.modified is not None:
            modified = int(time.mktime(self.modified.timetuple()))
        else:
            modified = 0
        url_template = (thumb and settings.PREVIEW_THUMBNAIL_URL or
                        settings.PREVIEW_FULL_URL)
        return url_template % (self.id / 1000, self.id, modified)

    @property
    def thumbnail_url(self):
        return self._image_url(thumb=True)

    @property
    def image_url(self):
        return self._image_url(thumb=False)
