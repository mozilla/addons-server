from django.db import models
from django_extensions.db.fields.json import JSONField

from olympia.amo.fields import PositiveAutoField
from olympia.amo.models import SearchMixin


def update_inc(initial, key, count):
    """Update or create a dict of `int` counters, for JSONField."""
    initial = initial or {}
    initial[key] = count + initial.get(key, 0)
    return initial


class DownloadCount(SearchMixin, models.Model):
    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey('addons.Addon', on_delete=models.CASCADE)

    count = models.PositiveIntegerField()
    date = models.DateField()
    sources = JSONField(db_column='src', null=True)

    ES_ALIAS_KEY = 'stats_download_counts'

    class Meta:
        db_table = 'download_counts'
        indexes = [
            # FIXME: some of these might redundant. See #5712
            models.Index(fields=('count',), name='count'),
            models.Index(fields=('addon',), name='addon_id'),
            models.Index(fields=('addon', 'count'), name='addon_and_count'),
            models.Index(fields=('addon', 'date'), name='addon_date_idx')
        ]
        constraints = [
            models.UniqueConstraint(fields=['date', 'addon'], name='date_2'),
        ]


class UpdateCount(SearchMixin, models.Model):
    id = PositiveAutoField(primary_key=True)
    addon = models.ForeignKey('addons.Addon', on_delete=models.CASCADE)
    count = models.PositiveIntegerField()
    date = models.DateField()
    versions = JSONField(db_column='version', null=True)
    statuses = JSONField(db_column='status', null=True)
    applications = JSONField(db_column='application', null=True)
    oses = JSONField(db_column='os', null=True)
    locales = JSONField(db_column='locale', null=True)

    ES_ALIAS_KEY = 'stats_update_counts'

    class Meta:
        db_table = 'update_counts'
        indexes = [
            # FIXME: some of these might redundant. See #5712
            models.Index(fields=('count',), name='count'),
            models.Index(fields=('addon',), name='addon_id'),
            models.Index(fields=('date',), name='date'),
            models.Index(fields=('addon', 'count'), name='addon_and_count'),
            models.Index(fields=('addon', 'date'), name='addon_date_idx')
        ]
