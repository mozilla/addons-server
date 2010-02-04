from django.db import models

import caching.base


class DownloadCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.IntegerField()
    date = models.DateField()
    src = models.TextField()

    objects = caching.base.CachingManager()

    class Meta:
        db_table = 'download_counts'


class UpdateCount(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    count = models.IntegerField()
    date = models.DateField()

    # Leave these out of queries if you can.
    application = models.TextField()
    locale = models.TextField()
    os = models.TextField()
    status = models.TextField()
    version = models.TextField()

    class Meta:
        db_table = 'update_counts'
