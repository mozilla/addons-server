from django.db import models

import caching.base

from .db import StatsDict, StatsDictField, StatsManager


class DownloadCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()

    # Leave this out of queries if you can.
    sources = StatsDictField(db_column='src', null=True)

    objects = StatsManager('date')

    class Meta:
        db_table = 'download_counts'


class UpdateCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.PositiveIntegerField()
    date = models.DateField()

    # Leave these out of queries if you can.
    versions = StatsDictField(db_column='version', null=True)
    statuses = StatsDictField(db_column='status', null=True)
    applications = StatsDictField(db_column='application', null=True)
    oses = StatsDictField(db_column='os', null=True)
    locales = StatsDictField(db_column='locale', null=True)

    objects = StatsManager('date')

    class Meta:
        db_table = 'update_counts'
