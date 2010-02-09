import datetime

from django.db import models

import caching.base

from amo.fields import DecimalCharField

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


class Contribution(caching.base.CachingMixin, models.Model):
    addon = models.ForeignKey('addons.Addon')
    amount = DecimalCharField(max_digits=9, decimal_places=2,
                              nullify_invalid=True, null=True)
    source = models.CharField(max_length=255, null=True)
    annoying = models.BooleanField()
    created = models.DateTimeField(auto_now_add=True)
    uuid = models.CharField(max_length=255, null=True)
    is_suggested = models.BooleanField()
    suggested_amount = DecimalCharField(max_digits=254, decimal_places=2,
                                        nullify_invalid=True, null=True)
    comment = models.CharField(max_length=255)
    transaction_id = models.CharField(max_length=255, null=True)
    post_data = StatsDictField(null=True)

    objects = StatsManager('created')

    class Meta:
        db_table = 'stats_contributions'

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
