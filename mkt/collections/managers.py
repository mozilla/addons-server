from amo.models import ManagerBase


class PublicCollectionsManager(ManagerBase):
    def get_query_set(self):
        qs = super(PublicCollectionsManager, self).get_query_set()
        return qs.filter(is_public=True)
