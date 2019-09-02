from django.db import models
from django_extensions.db.fields.json import JSONField

from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import SearchMixin


def update_inc(initial, key, count):
    """Update or create a dict of `int` counters, for JSONField."""
    initial = initial or {}
    initial[key] = count + initial.get(key, 0)
    return initial


class StatsSearchMixin(SearchMixin):

    ES_ALIAS_KEY = 'stats'


class DownloadCount(StatsSearchMixin, models.Model):
    id = PositiveAutoField(primary_key=True)
    # has an index `addon_id` on this column...
    addon = models.ForeignKey('addons.Addon', on_delete=models.CASCADE)

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
    id = PositiveAutoField(primary_key=True)
    # Has an index `addon_id` in our dev, stage and prod database
    addon = models.ForeignKey('addons.Addon', on_delete=models.CASCADE)
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
