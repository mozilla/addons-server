from django.conf import settings
from django.db import models

import amo
from apps.addons.models import Addon
from apps.editors.models import CannedResponse, EscalationQueue, RereviewQueue


class AppCannedResponseManager(amo.models.ManagerBase):
    def get_query_set(self):
        qs = super(AppCannedResponseManager, self).get_query_set()
        return qs.filter(type=amo.CANNED_RESPONSE_APP)


class AppCannedResponse(CannedResponse):
    objects = AppCannedResponseManager()

    class Meta:
        proxy = True


def cleanup_queues(sender, instance, **kwargs):
    RereviewQueue.objects.filter(addon=instance).delete()
    EscalationQueue.objects.filter(addon=instance).delete()


# Don't add this signal in if we are not in the marketplace.
if settings.MARKETPLACE:
    models.signals.post_delete.connect(cleanup_queues, sender=Addon,
                                       dispatch_uid='queue-addon-cleanup')
