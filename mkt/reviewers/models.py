import amo
from apps.editors.models import CannedResponse


class AppCannedResponseManager(amo.models.ManagerBase):
    def get_query_set(self):
        qs = super(AppCannedResponseManager, self).get_query_set()
        return qs.filter(type=amo.CANNED_RESPONSE_APP)


class AppCannedResponse(CannedResponse):
    objects = AppCannedResponseManager()

    class Meta:
        proxy = True
