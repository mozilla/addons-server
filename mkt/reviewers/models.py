from django.db import models

import amo
from apps.addons.models import Addon
from apps.editors.models import CannedResponse, EscalationQueue


class AppCannedResponseManager(amo.models.ManagerBase):
    def get_query_set(self):
        qs = super(AppCannedResponseManager, self).get_query_set()
        return qs.filter(type=amo.CANNED_RESPONSE_APP)


class AppCannedResponse(CannedResponse):
    objects = AppCannedResponseManager()

    class Meta:
        proxy = True


class RereviewQueue(amo.models.ModelBase):
    addon = models.ForeignKey(Addon, related_name='+')

    class Meta:
        db_table = 'rereview_queue'

    @classmethod
    def flag(cls, addon, event, message=None):
        cls.objects.get_or_create(addon=addon)
        if message:
            amo.log(event, addon, addon.current_version,
                    details={'comments': message})
        else:
            amo.log(event, addon, addon.current_version)


def cleanup_queues(sender, instance, **kwargs):
    RereviewQueue.objects.filter(addon=instance).delete()
    EscalationQueue.objects.filter(addon=instance).delete()


models.signals.post_delete.connect(cleanup_queues, sender=Addon,
                                   dispatch_uid='queue-addon-cleanup')
