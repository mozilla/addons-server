from django.db import models

import amo.models
from amo.urlresolvers import reverse


class BlocklistApp(amo.models.ModelBase):
    blitem = models.ForeignKey('BlocklistItem', related_name='app')
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


class BlocklistCA(amo.models.ModelBase):
    data = models.TextField()

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'blca'

    def flush_urls(self):
        return ['/blocklist*']  # no lang/app


class BlocklistDetail(amo.models.ModelBase):
    name = models.CharField(max_length=255)
    why = models.TextField()
    who = models.TextField()
    bug = models.URLField(verify_exists=False)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'bldetails'

    def __unicode__(self):
        return self.name


class BlocklistBase(object):

    @property
    def block_id(self):
        return '%s%s' % (self._type, self.details_id)

    def get_url_path(self):
        return reverse('blocked.detail', args=[self.block_id])

    def save(self, *args, **kw):
        for field in self._meta.fields:
            if isinstance(field, models.fields.CharField) and field.null:
                if getattr(self, field.attname, None) == '':
                    setattr(self, field.attname, None)
        return super(BlocklistBase, self).save(*args, **kw)


class BlocklistItem(BlocklistBase, amo.models.ModelBase):
    _type = 'i'
    guid = models.CharField(max_length=255, blank=True, null=True)
    min = models.CharField(max_length=255, blank=True, null=True)
    max = models.CharField(max_length=255, blank=True, null=True)
    os = models.CharField(max_length=255, blank=True, null=True)
    severity = models.SmallIntegerField(blank=True, null=True)
    details = models.OneToOneField(BlocklistDetail, null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'blitems'

    def __unicode__(self):
        return '%s: %s - %s' % (self.guid, self.min, self.max)

    def flush_urls(self):
        return ['/blocklist*']  # no lang/app


class BlocklistPlugin(BlocklistBase, amo.models.ModelBase):
    _type = 'p'
    name = models.CharField(max_length=255, blank=True, null=True)
    guid = models.CharField(max_length=255, blank=True, null=True)
    min = models.CharField(max_length=255, blank=True, null=True)
    max = models.CharField(max_length=255, blank=True, null=True)
    os = models.CharField(max_length=255, blank=True, null=True)
    xpcomabi = models.CharField(max_length=255, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    filename = models.CharField(max_length=255, blank=True, null=True)
    severity = models.SmallIntegerField(blank=True, null=True)
    vulnerability_status = models.SmallIntegerField(blank=True, null=True,
                                                    choices=
                                                    ((1, 'update available'),
                                                     (2, 'update unavailable')))
    details = models.OneToOneField(BlocklistDetail, null=True)

    class Meta(amo.models.ModelBase.Meta):
        db_table = 'blplugins'

    def __unicode__(self):
        return '%s: %s - %s' % (self.name or self.guid or self.filename,
                                    self.min, self.max)

    @property
    def get_vulnerability_status(self):
        """Returns vulnerability status per bug 778365

        Returns None when criteria aren't met so jinja2 excludes it from when
        using the attrs filter.
        """
        if self.severity == 0 and self.vulnerability_status in (1,2):
            return self.vulnerability_status

    def flush_urls(self):
        return ['/blocklist*']  # no lang/app


class BlocklistGfx(BlocklistBase, amo.models.ModelBase):
    _type = 'g'
    guid = models.CharField(max_length=255, blank=True, null=True)
    os = models.CharField(max_length=255, blank=True, null=True)
    vendor = models.CharField(max_length=255, blank=True, null=True)
    devices = models.CharField(max_length=255, blank=True, null=True)
    feature = models.CharField(max_length=255, blank=True, null=True)
    feature_status = models.CharField(max_length=255, blank=True, null=True)
    driver_version = models.CharField(max_length=255, blank=True, null=True)
    driver_version_comparator = models.CharField(max_length=255, blank=True,
                                                 null=True)
    details = models.OneToOneField(BlocklistDetail, null=True)

    class Meta:
        db_table = 'blgfxdrivers'

    def __unicode__(self):
        return '%s: %s : %s : %s' % (self.guid, self.os, self.vendor,
                                     self.devices)

    def flush_urls(self):
        return ['/blocklist*']  # no lang/app
