from django.db import models

import amo


class BlocklistApp(amo.ModelBase):
    blitem = models.ForeignKey('BlocklistItem')
    guid = models.CharField(max_length=255, blank=True, db_index=True)
    min = models.CharField(max_length=255, blank=True)
    max = models.CharField(max_length=255, blank=True)

    class Meta(amo.ModelBase.Meta):
        db_table = 'blapps'

    def __unicode__(self):
        return '%s: %s - %s' % (self.guid, self.min, self.max)


class BlocklistItem(amo.ModelBase):
    guid = models.CharField(max_length=255, blank=True)
    min = models.CharField(max_length=255, blank=True)
    max = models.CharField(max_length=255, blank=True)
    os = models.CharField(max_length=255, blank=True)
    severity = models.SmallIntegerField(null=True)

    class Meta(amo.ModelBase.Meta):
        db_table = 'blitems'

    def __unicode__(self):
        return '%s: %s - %s' % (self.guid, self.min, self.max)


class BlocklistPlugin(amo.ModelBase):
    name = models.CharField(max_length=255, blank=True)
    guid = models.CharField(max_length=255, blank=True)
    min = models.CharField(max_length=255, blank=True)
    max = models.CharField(max_length=255, blank=True)
    os = models.CharField(max_length=255, blank=True)
    xpcomabi = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255, blank=True)
    filename = models.CharField(max_length=255, blank=True)
    severity = models.SmallIntegerField(null=True)

    class Meta(amo.ModelBase.Meta):
        db_table = 'blplugins'

    def __unicode__(self):
        return '%s: %s - %s' % (self.name or self.guid or self.filename,
                                    self.min, self.max)
