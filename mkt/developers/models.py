from django.db import models

import amo
from devhub.models import ActivityLog
from users.models import UserForeignKey


class BlueViaConfig(amo.models.ModelBase):
    user = UserForeignKey()
    developer_id = models.CharField(max_length=64)

    class Meta:
        db_table = 'bluevia'
        unique_together = ('user', 'developer_id')


class AddonBlueViaConfig(amo.models.ModelBase):
    addon = models.OneToOneField('addons.Addon',
                                 related_name='addonblueviaconfig')
    bluevia_config = models.ForeignKey(BlueViaConfig)
    status = models.PositiveIntegerField(choices=amo.INAPP_STATUS_CHOICES,
                                         default=amo.INAPP_STATUS_INACTIVE,
                                         db_index=True)

    class Meta:
        db_table = 'addon_bluevia'
        unique_together = ('addon', 'bluevia_config')
