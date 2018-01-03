from django_statsd.clients import statsd
from rest_framework.mixins import ListModelMixin
from rest_framework.viewsets import GenericViewSet
from waffle import switch_is_active

from olympia.addons.models import Addon
from olympia.discovery.data import discopane_items
from olympia.discovery.serializers import DiscoverySerializer
from olympia.discovery.utils import get_recommendations, replace_extensions


class DiscoveryViewSet(ListModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = DiscoverySerializer

    def get_param(self, name):
        return self.kwargs.get(name) or self.request.GET.get(name)

    def get_discopane_items(self):
        if not getattr(self, 'discopane_items', None):
            telemetry_id = self.get_param('telemetry-client-id')
            self.discopane_items = discopane_items
            if switch_is_active('disco-recommendations') and telemetry_id:
                recommendations = get_recommendations(
                    telemetry_id, self.get_param('lang'),
                    self.get_param('platform'))
                if recommendations:
                    # if we got some recommendations then replace the
                    # extensions in discopane_items with them.
                    # Leave the non-extensions (personas) alone.
                    self.discopane_items = replace_extensions(
                        discopane_items, recommendations)
        return self.discopane_items

    def get_queryset(self):
        ids = [item.addon_id for item in self.get_discopane_items()]
        # FIXME: Implement using ES. It would look like something like this,
        # with a specific serializer that inherits from the ES one + code to
        # build the dict:
        # es = amo.search.get_es()
        # es.mget({'ids': ids}, index=AddonIndexer.get_index_alias(),
        #         doc_type=AddonIndexer.get_doctype_name())
        addons = Addon.objects.public().in_bulk(ids)

        # Patch items to add addons.
        result = []
        for item in self.get_discopane_items():
            try:
                item.addon = addons[item.addon_id]
                result.append(item)
            except KeyError:
                # Ignore this missing add-on, but increment a counter so we
                # know something happened.
                statsd.incr('discovery.api.missing_item')
        return result
