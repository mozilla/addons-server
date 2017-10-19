import datetime

from django.db import models
from django.utils.translation import (
    activate, to_locale, get_language)

import caching.base
from babel import Locale, numbers
from jinja2.filters import do_dictsort

from olympia import amo
from olympia.amo.models import SearchMixin
from olympia.amo.utils import get_locale_from_lang

from .db import LargeStatsDictField, StatsDictField


def update_inc(initial, key, count):
    """Update or create a dict of `int` counters, for StatsDictFields."""
    initial = initial or {}
    initial[key] = count + initial.get(key, 0)
    return initial


class AddonCollectionCount(models.Model):
    addon = models.ForeignKey('addons.Addon')
    collection = models.ForeignKey('bandwagon.Collection')
    count = models.PositiveIntegerField()
    date = models.DateField()

    class Meta:
        db_table = 'stats_addons_collections_counts'


class StatsSearchMixin(SearchMixin):

    ES_ALIAS_KEY = 'stats'


class CollectionCount(StatsSearchMixin, models.Model):
    collection = models.ForeignKey('bandwagon.Collection')

    # index name in our dev/stage/prod database: `count`
    count = models.PositiveIntegerField(db_index=True)

    # index name in our dev/stage/prod database: `date`
    date = models.DateField(db_index=True)

    class Meta:
        db_table = 'stats_collections_counts'


class CollectionStats(models.Model):
    """In the running for worst-named model ever."""
    collection = models.ForeignKey('bandwagon.Collection')
    name = models.CharField(max_length=255, null=True)
    count = models.PositiveIntegerField()
    date = models.DateField()

    class Meta:
        db_table = 'stats_collections'


class DownloadCount(StatsSearchMixin, models.Model):
    # has an index `addon_id` on this column...
    addon = models.ForeignKey('addons.Addon')

    # has an index named `count` in dev, stage and prod
    count = models.PositiveIntegerField(db_index=True)
    date = models.DateField()
    sources = StatsDictField(db_column='src', null=True)

    class Meta:
        db_table = 'download_counts'

        # additional indices on this table (in dev, stage and prod):
        # * KEY `addon_and_count` (`addon_id`,`count`)
        # * KEY `addon_date_idx` (`addon_id`,`date`)

        # in our (dev, stage and prod) database:
        # UNIQUE KEY `date_2` (`date`,`addon_id`)
        unique_together = ('date', 'addon')


class UpdateCount(StatsSearchMixin, models.Model):
    # Has an index `addon_id` in our dev, stage and prod database
    addon = models.ForeignKey('addons.Addon')
    # Has an index named `count` in our dev, stage and prod database
    count = models.PositiveIntegerField(db_index=True)
    # Has an index named `date` in our dev, stage and prod database
    date = models.DateField(db_index=True)
    versions = StatsDictField(db_column='version', null=True)
    statuses = StatsDictField(db_column='status', null=True)
    applications = LargeStatsDictField(db_column='application', null=True)
    oses = StatsDictField(db_column='os', null=True)
    locales = StatsDictField(db_column='locale', null=True)

    class Meta:
        db_table = 'update_counts'

        # Additional indices on this table (on dev, stage and prod):
        # * KEY `addon_and_count` (`addon_id`,`count`)
        # * KEY `addon_date_idx` (`addon_id`,`date`)


class ThemeUpdateCountManager(models.Manager):

    def get_range_days_avg(self, start, end, *extra_fields):
        """Return a a ValuesListQuerySet containing the addon_id and popularity
        for each theme where popularity is the average number of users (count)
        over the given range of days passed as start / end arguments.

        If extra_fields are passed, then the list of fields is returned in the
        queryset, inserted after addon_id but before popularity."""
        return (self.values_list('addon_id', *extra_fields)
                    .filter(date__range=[start, end])
                    .annotate(avg=models.Avg('count')))


class ThemeUpdateCount(StatsSearchMixin, models.Model):
    """Daily users taken from the ADI data (coming from Hive)."""
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()

    objects = ThemeUpdateCountManager()

    class Meta:
        db_table = 'theme_update_counts'


class ThemeUpdateCountBulk(models.Model):
    """Used by the update_theme_popularity_movers command for perf reasons.

    First bulk inserting all the averages over the last week and last three
    weeks in this table allows us to bulk update (instead of running an update
    per Persona).

    """
    persona_id = models.PositiveIntegerField()
    popularity = models.PositiveIntegerField()
    movers = models.FloatField()

    class Meta:
        db_table = 'theme_update_counts_bulk'


class ContributionError(Exception):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class Contribution(amo.models.ModelBase):
    # TODO(addon): figure out what to do when we delete the add-on.
    addon = models.ForeignKey('addons.Addon')
    amount = models.DecimalField(max_digits=9, decimal_places=2, null=True)
    currency = models.CharField(max_length=3,
                                choices=do_dictsort(amo.PAYPAL_CURRENCIES),
                                default=amo.CURRENCY_DEFAULT)
    source = models.CharField(max_length=255, null=True)
    source_locale = models.CharField(max_length=10, null=True)
    # This is the external id that you can communicate to the world.
    uuid = models.CharField(max_length=255, null=True, db_index=True)
    comment = models.CharField(max_length=255)
    # This is the internal transaction id between us and a provider,
    # for example paypal or solitude.
    transaction_id = models.CharField(max_length=255, null=True, db_index=True)
    paykey = models.CharField(max_length=255, null=True)
    post_data = StatsDictField(null=True)

    # Voluntary Contribution specific.
    charity = models.ForeignKey('addons.Charity', null=True)
    annoying = models.PositiveIntegerField(default=0,
                                           choices=amo.CONTRIB_CHOICES,)
    is_suggested = models.BooleanField(default=False)
    suggested_amount = models.DecimalField(max_digits=9, decimal_places=2,
                                           null=True)

    class Meta:
        db_table = 'stats_contributions'

    def __unicode__(self):
        return u'%s: %s' % (self.addon.name, self.amount)

    @property
    def date(self):
        try:
            return datetime.date(self.created.year,
                                 self.created.month, self.created.day)
        except AttributeError:
            # created may be None
            return None

    @property
    def contributor(self):
        try:
            return u'%s %s' % (self.post_data['first_name'],
                               self.post_data['last_name'])
        except (TypeError, KeyError):
            # post_data may be None or missing a key
            return None

    @property
    def email(self):
        try:
            return self.post_data['payer_email']
        except (TypeError, KeyError):
            # post_data may be None or missing a key
            return None

    def _switch_locale(self):
        if self.source_locale:
            lang = self.source_locale
        else:
            lang = self.addon.default_locale
        activate(lang)
        return Locale(to_locale(lang))

    def get_amount_locale(self, locale=None):
        """Localise the amount paid into the current locale."""
        if not locale:
            lang = get_language()
            locale = get_locale_from_lang(lang)
        return numbers.format_currency(self.amount or 0,
                                       self.currency or 'USD',
                                       locale=locale)


class GlobalStat(caching.base.CachingMixin, models.Model):
    name = models.CharField(max_length=255)
    count = models.IntegerField()
    date = models.DateField()

    objects = caching.base.CachingManager()

    class Meta:
        db_table = 'global_stats'
        unique_together = ('name', 'date')
        get_latest_by = 'date'


class ThemeUserCount(StatsSearchMixin, models.Model):
    """Theme popularity (weekly average of users).

    This is filled in by a cron job reading the popularity from the theme
    (Persona).

    """
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()

    class Meta:
        db_table = 'theme_user_counts'
        index_together = ('date', 'addon')
