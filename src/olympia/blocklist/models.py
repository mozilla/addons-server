from django.db import models

from olympia.amo.models import ModelBase
from olympia.amo.urlresolvers import reverse


class BlocklistApp(ModelBase):
    blitem = models.ForeignKey('BlocklistItem', related_name='app', blank=True,
                               null=True)
    blplugin = models.ForeignKey('BlocklistPlugin', related_name='app',
                                 blank=True, null=True)
    guid = models.CharField(max_length=255, blank=True, db_index=True,
                            null=True)
    min = models.CharField(max_length=255, blank=True, null=True)
    max = models.CharField(max_length=255, blank=True, null=True)

    class Meta(ModelBase.Meta):
        db_table = 'blapps'

    def __unicode__(self):
        return '%s: %s - %s' % (self.guid, self.min, self.max)


class BlocklistCA(ModelBase):
    data = models.TextField()

    class Meta(ModelBase.Meta):
        db_table = 'blca'


class BlocklistDetail(ModelBase):
    name = models.CharField(max_length=255)
    why = models.TextField()
    who = models.TextField()
    bug = models.URLField()

    class Meta(ModelBase.Meta):
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


class BlocklistItem(BlocklistBase, ModelBase):
    _type = 'i'
    guid = models.CharField(max_length=255, blank=True, null=True)
    min = models.CharField(max_length=255, blank=True, null=True)
    max = models.CharField(max_length=255, blank=True, null=True)
    os = models.CharField(max_length=255, blank=True, null=True)
    severity = models.SmallIntegerField(blank=True, null=True)
    details = models.OneToOneField(BlocklistDetail, null=True)
    name = models.CharField(max_length=255, blank=True, null=True)
    creator = models.CharField(max_length=255, blank=True, null=True)
    homepage_url = models.URLField(blank=True, null=True)
    update_url = models.URLField(blank=True, null=True)

    class Meta(ModelBase.Meta):
        db_table = 'blitems'

    def __unicode__(self):
        return '%s: %s - %s' % (self.guid, self.min, self.max)


class BlocklistPlugin(BlocklistBase, ModelBase):
    _type = 'p'
    name = models.CharField(max_length=255, blank=True, null=True)
    guid = models.CharField(max_length=255, blank=True, db_index=True,
                            null=True)
    min = models.CharField(max_length=255, blank=True, null=True)
    max = models.CharField(max_length=255, blank=True, null=True)
    os = models.CharField(max_length=255, blank=True, null=True)
    xpcomabi = models.CharField(max_length=255, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    filename = models.CharField(max_length=255, blank=True, null=True)
    severity = models.SmallIntegerField(blank=True, null=True)
    vulnerability_status = models.SmallIntegerField(
        blank=True, null=True,
        choices=((1, 'update available'),
                 (2, 'update unavailable')))
    info_url = models.URLField(blank=True, null=True)
    details = models.OneToOneField(BlocklistDetail, null=True)

    class Meta(ModelBase.Meta):
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
        if self.severity == 0 and self.vulnerability_status in (1, 2):
            return self.vulnerability_status


class BlocklistGfx(BlocklistBase, ModelBase):
    _type = 'g'
    guid = models.CharField(max_length=255, blank=True, null=True)
    os = models.CharField(max_length=255, blank=True, null=True)
    vendor = models.CharField(max_length=255, blank=True, null=True)
    devices = models.CharField(max_length=255, blank=True, null=True)
    feature = models.CharField(max_length=255, blank=True, null=True)
    feature_status = models.CharField(max_length=255, blank=True, null=True)
    driver_version = models.CharField(max_length=255, blank=True, null=True)
    driver_version_max = models.CharField(
        max_length=255, blank=True, null=True)
    driver_version_comparator = models.CharField(max_length=255, blank=True,
                                                 null=True)
    hardware = models.CharField(max_length=255, blank=True, null=True)
    details = models.OneToOneField(BlocklistDetail, null=True)
    application_min = models.CharField(max_length=255, blank=True, null=True)
    application_max = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'blgfxdrivers'

    def __unicode__(self):
        return '%s: %s : %s : %s' % (self.guid, self.os, self.vendor,
                                     self.devices)


class BlocklistIssuerCert(BlocklistBase, ModelBase):
    _type = 'c'
    issuer = models.TextField()  # Annoyingly, we can't know the size.
    serial = models.CharField(max_length=255)
    details = models.OneToOneField(BlocklistDetail)

    class Meta:
        db_table = 'blissuercert'

    def __unicode__(self):
        return unicode(self.details.name)


class BlocklistPref(ModelBase):
    """Preferences which should be reset when a blocked item is detected."""

    blitem = models.ForeignKey('BlocklistItem', related_name='prefs')
    pref = models.CharField(max_length=255)

    class Meta:
        db_table = 'blitemprefs'
