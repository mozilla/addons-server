
from django.db import models
from django_extensions.db.fields.json import JSONField

from olympia.amo.models import SearchMixin


def update_inc(initial, key, count):
    """Update or create a dict of `int` counters, for JSONField."""
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
    sources = JSONField(db_column='src', null=True)

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
    versions = JSONField(db_column='version', null=True)
    statuses = JSONField(db_column='status', null=True)
    applications = JSONField(db_column='application', null=True)
    oses = JSONField(db_column='os', null=True)
    locales = JSONField(db_column='locale', null=True)

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


class GlobalStat(models.Model):
    name = models.CharField(max_length=255)
    count = models.IntegerField()
    date = models.DateField()

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
