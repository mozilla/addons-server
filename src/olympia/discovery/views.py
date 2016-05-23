from rest_framework.mixins import ListModelMixin
from rest_framework.viewsets import GenericViewSet

from olympia.addons.models import Addon
from olympia.discovery.data import discopane_items
from olympia.discovery.serializers import DiscoverySerializer


class DiscoveryViewSet(ListModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = DiscoverySerializer
    queryset = Addon.objects.public()

    def get_queryset(self):
        ids = [item.addon_id for item in discopane_items]
        # FIXME: Implement using ES. It would look like something like this,
        # with a specific serializer that inherits from the ES one + code to
        # build the dict:
        # es = amo.search.get_es()
        # es.mget({'ids': ids}, index=AddonIndexer.get_index_alias(),
        #         doc_type=AddonIndexer.get_doctype_name())
        addons = self.queryset.in_bulk(ids)

        # Patch items to add addons.
        result = []
        for item in discopane_items:
            try:
                item.addon = addons[item.addon_id]
                result.append(item)
            except KeyError:
                pass
        return result
