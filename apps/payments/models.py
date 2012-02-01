import amo
from django.db import models


class InappConfig(amo.models.ModelBase):
    addon = models.ForeignKey('addons.Addon', unique=False)
    chargeback_url = models.URLField(verify_exists=False, blank=True)
    postback_url = models.URLField(verify_exists=False, blank=True)
    private_key = models.CharField(max_length=255, unique=True)
    public_key = models.CharField(max_length=255, unique=True, db_index=True)
    status = models.PositiveIntegerField(choices=amo.INAPP_STATUS_CHOICES,
                                         default=amo.INAPP_STATUS_INACTIVE,
                                         db_index=True)

    class Meta:
        db_table = 'addon_inapp'

    def is_active(self):
        return self.status == amo.INAPP_STATUS_ACTIVE

    def __unicode__(self):
        return u'%s: %s' % (self.addon, self.status)

    @classmethod
    def any_active(cls, addon):
        """Tells you if there are any active keys for this addon."""
        return (cls.objects.filter(addon=addon,
                                   status=amo.INAPP_STATUS_ACTIVE)
                          .exists())

    def save(self, *args, **kw):
        current = InappConfig.any_active(self.addon)
        if current:
            raise ValueError, 'You can only have one active config'
        super(InappConfig, self).save(*args, **kw)
