from django.db import models

import amo.models


class BlocklistApp(amo.models.ModelBase):
    blitem = models.ForeignKey('BlocklistItem')
    guid = models.CharField(max_length=255, blank=True, db_index=True,
                            null=True)
    min = models.CharField(max_length=255, blank=True, null=True)
    max = models.CharField(max_length=255, blank=True, null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'blapps'

    def __unicode__(self):
        return '%s: %s - %s' % (self.guid, self.min, self.max)

    def flush_urls(self):
        return ['/blocklist*']  # no lang/app


class BlocklistItem(amo.models.ModelBase):
    guid = models.CharField(max_length=255, blank=True, null=True)
    min = models.CharField(max_length=255, blank=True, null=True)
    max = models.CharField(max_length=255, blank=True, null=True)
    os = models.CharField(max_length=255, blank=True, null=True)
    severity = models.SmallIntegerField(null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'blitems'

    def __unicode__(self):
        return '%s: %s - %s' % (self.guid, self.min, self.max)

    def flush_urls(self):
        return ['/blocklist*']  # no lang/app


class BlocklistPlugin(amo.models.ModelBase):
    name = models.CharField(max_length=255, blank=True, null=True)
    guid = models.CharField(max_length=255, blank=True, null=True)
    min = models.CharField(max_length=255, blank=True, null=True)
    max = models.CharField(max_length=255, blank=True, null=True)
    os = models.CharField(max_length=255, blank=True, null=True)
    xpcomabi = models.CharField(max_length=255, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    filename = models.CharField(max_length=255, blank=True, null=True)
    severity = models.SmallIntegerField(null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'blplugins'

    def __unicode__(self):
        return '%s: %s - %s' % (self.name or self.guid or self.filename,
                                    self.min, self.max)

    def flush_urls(self):
        return ['/blocklist*']  # no lang/app
