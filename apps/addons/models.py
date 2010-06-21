import collections
from datetime import date
import itertools
import json
import time

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum

import caching.base as caching

import amo.models
from amo.fields import DecimalCharField
from amo.utils import urlparams, sorted_groupby, JSONEncoder
from amo.urlresolvers import reverse
from reviews.models import Review
from stats.models import Contribution as ContributionStats, ShareCountTotal
from translations.fields import (TranslatedField, PurifiedField,
                                 LinkifiedField, translations_with_fallback)
from users.models import UserProfile
from versions.models import Version

from . import query


class AddonManager(amo.models.ManagerBase):

    def get_query_set(self):
        qs = super(AddonManager, self).get_query_set()
        qs = qs._clone(klass=query.IndexQuerySet)
        return qs.transform(Addon.transformer)

    def public(self):
        """Get public add-ons only"""
        return self.filter(inactive=False, status=amo.STATUS_PUBLIC)

    def unreviewed(self):
        """Get only unreviewed add-ons"""
        return self.filter(inactive=False,
                           status__in=amo.UNREVIEWED_STATUSES)

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
        not inactive.  Personas and self-hosted add-ons will be returned too.
        """
        if len(status) == 0:
            status = [amo.STATUS_PUBLIC]

        has_version = Q(appsupport__app=app.id,
                        _current_version__isnull=False)
        is_weird = Q(type=amo.ADDON_PERSONA) | Q(status=amo.STATUS_LISTED)
        return self.filter(has_version | is_weird,
                           inactive=False, status__in=status)


class Addon(amo.models.ModelBase):
    STATUS_CHOICES = amo.STATUS_CHOICES.items()
    CONTRIB_CHOICES = sorted(amo.CONTRIB_CHOICES.items())

    guid = models.CharField(max_length=255, unique=True, null=True)
    name = TranslatedField()
    default_locale = models.CharField(max_length=10,
                                      default=settings.LANGUAGE_CODE,
                                      db_column='defaultlocale')

    type = models.PositiveIntegerField(db_column='addontype_id')
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
            default=0, db_column='weeklydownloads', db_index=True)
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

    _current_version = models.ForeignKey(Version, related_name='___ignore',
            db_column='current_version', null=True)

    objects = AddonManager()

    class Meta:
        db_table = 'addons'

    def __unicode__(self):
        return '%s: %s' % (self.id, self.name)

    def get_url_path(self):
        return reverse('addons.detail', args=(self.id,))

    def meet_the_dev_url(self):
        return reverse('addons.meet', args=[self.id])

    @property
    def reviews_url(self):
        return reverse('reviews.list', args=(self.id,))

    def type_url(self):
        """The url for this add-on's AddonType."""
        return AddonType(self.type).get_url_path()

    @amo.cached_property(writable=True)
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
        return Review.objects.filter(version__addon=self, reply_to=None)

    def get_current_version(self):
        """Retrieves the latest version of an addon."""
        if self.type == amo.ADDON_PERSONA:
            return
        try:
            if self.status == amo.STATUS_PUBLIC:
                status = [self.status]
            elif self.status == amo.STATUS_LISTED:
                return self.versions.all()[0]
            else:
                status = amo.VALID_STATUSES

            status_list = ','.join(map(str, status))
            return self.versions.filter(
                files__status__in=status).extra(
                where=["""
                    NOT EXISTS (
                        SELECT 1 FROM versions as v2
                        INNER JOIN files AS f2 ON (f2.version_id = v2.id)
                        WHERE v2.id = versions.id
                        AND f2.status NOT IN (%s))
                    """ % status_list])[0]

        except (IndexError, Version.DoesNotExist):
            return None

    def update_current_version(self):
        "Returns true if we updated the current_version field."
        current_version = self.get_current_version()
        if current_version != self._current_version:
            self._current_version = current_version
            self.save()
            return True
        return False

    @property
    def current_version(self):
        "Returns the current_version field or updates it if needed."
        if self.type == amo.ADDON_PERSONA:
            return
        if not self._current_version:
            self.update_current_version()
        return self._current_version

    @staticmethod
    def transformer(addons):
        if not addons:
            return

        addon_dict = dict((a.id, a) for a in addons)
        personas = [a for a in addons if a.type == amo.ADDON_PERSONA]
        addons = [a for a in addons if a.type != amo.ADDON_PERSONA]

        version_ids = filter(None, (a._current_version_id for a in addons))
        versions = list(Version.objects.filter(id__in=version_ids))
        Version.transformer(versions)
        for version in versions:
            addon_dict[version.addon_id]._current_version = version

        # Attach listed authors.
        q = (UserProfile.objects.no_cache()
             .filter(addons__in=addons, addonuser__listed=True)
             .extra(select={'addon_id': 'addons_users.addon_id',
                            'position': 'addons_users.position'}))
        q = sorted(q, key=lambda u: (u.addon_id, u.position))
        for addon_id, users in itertools.groupby(q, key=lambda u: u.addon_id):
            addon_dict[addon_id].listed_authors = list(users)

        for persona in Persona.objects.no_cache().filter(addon__in=personas):
            addon_dict[persona.addon_id].persona = persona
            addon_dict[persona.addon_id].listed_authors = []

        # Personas need categories for the JSON dump.
        Category.transformer(personas)

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
            if self.type == amo.ADDON_THEME:
                icon = 'default-theme.png'
            else:
                icon = 'default-addon.png'
            return settings.MEDIA_URL + 'img/amo2009/icons/' + icon

        else:
            return settings.ADDON_ICON_URL % (
                    self.id, int(time.mktime(self.modified.timetuple())))

    @property
    def authors_other_addons(self):
        """
        Return other addons by the author(s) of this addon
        """
        return (Addon.objects.valid().only_translations()
                  .exclude(id=self.id)
                  .filter(addonuser__listed=True,
                          authors__in=self.listed_authors).distinct())

    @property
    def contribution_url(self, lang=settings.LANGUAGE_CODE,
                         app=settings.DEFAULT_APP):
        return '/%s/%s/addons/contribute/%d' % (lang, app, self.id)

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

    def is_selfhosted(self):
        return self.status == amo.STATUS_LISTED

    def is_unreviewed(self):
        return self.status in amo.UNREVIEWED_STATUSES

    @caching.cached_method
    def is_featured(self, app, lang):
        """is add-on globally featured for this app and language?"""
        locale_filter = (Q(feature__locale=lang) |
                         Q(feature__locale__isnull=True) |
                         Q(feature__locale=''))
        return Addon.objects.featured(app).filter(
            locale_filter, pk=self.pk).exists()

    @caching.cached_method
    def is_category_featured(self, app, lang):
        """is add-on featured in any category for this app?"""
        # XXX should probably take feature_locales under consideration, even
        # though remora didn't do that
        return AddonCategory.objects.filter(
            addon=self, feature=True,
            category__application__id=app.id).exists()

    @amo.cached_property
    def tags_partitioned_by_developer(self):
        "Returns a tuple of developer tags and user tags for this addon."
        # TODO(davedash): We can't cache these tags until /tags/ are moved
        # into Zamboni.
        tags = self.tags.not_blacklisted().no_cache()
        user_tags = tags.exclude(addon_tags__user__in=self.listed_authors)
        dev_tags = tags.exclude(id__in=[t.id for t in user_tags])
        return dev_tags, user_tags

    @amo.cached_property
    def compatible_apps(self):
        """Shortcut to get compatible apps for the current version."""
        if self.current_version:
            return self.current_version.compatible_apps
        else:
            return {}

    @caching.cached_method
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
        return AddonUser.objects.filter(addon=self, user=user,
                                        role__in=roles).exists()

    @property
    def takes_contributions(self):
        # TODO(jbalogh): config.paypal_disabled
        return self.wants_contributions and self.paypal_id

    @property
    def has_eula(self):
        return self.eula and self.eula.localized_string

    @caching.cached_method
    def share_counts(self):
        rv = collections.defaultdict(int)
        rv.update(ShareCountTotal.objects.filter(addon=self)
                  .values_list('service', 'count'))
        return rv


class Persona(caching.CachingMixin, models.Model):
    """Personas-specific additions to the add-on model."""
    addon = models.OneToOneField(Addon)
    persona_id = models.PositiveIntegerField(db_index=True)
    # name: deprecated in favor of Addon model's name field
    # description: deprecated, ditto
    header = models.CharField(max_length=64, null=True)
    footer = models.CharField(max_length=64, null=True)
    accentcolor = models.CharField(max_length=10, null=True)
    textcolor = models.CharField(max_length=10, null=True)
    author = models.CharField(max_length=32, null=True)
    display_username = models.CharField(max_length=32, null=True)
    submit = models.DateTimeField(null=True)
    approve = models.DateTimeField(null=True)

    movers = models.FloatField(null=True, db_index=True)
    popularity = models.IntegerField(null=False, default=0, db_index=True)
    license = models.ForeignKey('versions.License', null=True)

    objects = caching.CachingManager()

    class Meta:
        db_table = 'personas'

    def __unicode__(self):
        return unicode(self.addon.name)

    def _image_url(self, filename, ssl=True):
        base_url = (settings.PERSONAS_IMAGE_URL_SSL if ssl else
                    settings.PERSONAS_IMAGE_URL)
        units = self.persona_id % 10
        tens = (self.persona_id // 10) % 10
        return base_url % {
            'units': units, 'tens': tens, 'file': filename,
            'id': self.persona_id,
        }

    @amo.cached_property
    def thumb_url(self):
        """URL to Persona's thumbnail preview."""
        return self._image_url('preview.jpg')

    @amo.cached_property
    def preview_url(self):
        """URL to Persona's big, 680px, preview."""
        return self._image_url('preview_large.jpg')

    @amo.cached_property
    def json_data(self):
        """Persona JSON Data for Browser/extension preview."""
        hexcolor = lambda color: '#%s' % color
        addon = self.addon
        return json.dumps({
            'id': unicode(self.persona_id),  # Personas dislikes ints
            'name': addon.name,
            'accentcolor': hexcolor(self.accentcolor),
            'textcolor': hexcolor(self.textcolor),
            'category': (addon.all_categories[0].name if
                         addon.all_categories else ''),
            'author': self.author,
            'description': addon.description,
            'header': self._image_url(self.header, ssl=False),
            'footer': self._image_url(self.footer, ssl=False),
            'headerURL': self._image_url(self.header, ssl=False),
            'footerURL': self._image_url(self.footer, ssl=False),
            'previewURL': self.preview_url,
            'iconURL': self.thumb_url,
        }, separators=(',', ':'), cls=JSONEncoder)


class AddonCategory(caching.CachingMixin, models.Model):
    addon = models.ForeignKey(Addon)
    category = models.ForeignKey('Category')
    feature = models.BooleanField(default=False)
    feature_locales = models.CharField(max_length=255, default='', null=True)

    objects = caching.CachingManager()

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
        return qs['raised'] or 0

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

    @classmethod
    def scores(cls, addon_ids):
        """Get a mapping of {addon: {other_addon: score}} for each add-on."""
        d = {}
        q = (AddonRecommendation.objects.filter(addon__in=addon_ids)
             .values('addon', 'other_addon', 'score'))
        for addon, rows in sorted_groupby(q, key=lambda x: x['addon']):
            d[addon] = dict((r['other_addon'], r['score']) for r in rows)
        return d


class AddonType(amo.models.ModelBase):
    name = TranslatedField()
    name_plural = TranslatedField()
    description = TranslatedField()

    class Meta:
        db_table = 'addontypes'

    def __unicode__(self):
        return unicode(self.name)

    def get_url_path(self):
        try:
            type = amo.ADDON_SLUGS[self.id]
        except KeyError:
            return None
        return reverse('browse.%s' % type)


class AddonUser(caching.CachingMixin, models.Model):
    AUTHOR_CHOICES = amo.AUTHOR_CHOICES.items()

    addon = models.ForeignKey(Addon)
    user = models.ForeignKey('users.UserProfile')
    role = models.SmallIntegerField(default=amo.AUTHOR_ROLE_OWNER,
                                    choices=AUTHOR_CHOICES)
    listed = models.BooleanField(default=True)
    position = models.IntegerField(default=0)

    objects = caching.CachingManager()

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
    type = models.PositiveIntegerField(db_column='addontype_id')
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
        try:
            type = amo.ADDON_SLUGS[self.type]
        except KeyError:
            type = amo.ADDON_SLUGS[amo.ADDON_EXTENSION]
        return reverse('browse.%s' % type, args=[self.slug])

    @staticmethod
    def transformer(addons):
        qs = (Category.uncached.filter(addons__in=addons)
              .extra(select={'addon_id': 'addons_categories.addon_id'}))
        cats = dict((addon_id, list(cs))
                    for addon_id, cs in sorted_groupby(qs, 'addon_id'))
        for addon in addons:
            addon.all_categories = cats.get(addon.id, [])


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

    def as_dict(self, src=None):
        d = {'full': urlparams(self.image_url, src=src),
             'thumbnail': urlparams(self.thumbnail_url, src=src),
             'caption': unicode(self.caption)}
        return d

    @property
    def thumbnail_url(self):
        return self._image_url(thumb=True)

    @property
    def image_url(self):
        return self._image_url(thumb=False)


class AppSupport(amo.models.ModelBase):
    """Cache to tell us if an add-on's current version supports an app."""
    addon = models.ForeignKey(Addon)
    app = models.ForeignKey('applications.Application')

    class Meta:
        db_table = 'appsupport'
