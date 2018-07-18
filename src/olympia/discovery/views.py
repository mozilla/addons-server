from django_statsd.clients import statsd
from rest_framework.mixins import ListModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from waffle import switch_is_active

from olympia import amo
from olympia.addons.models import Addon
from olympia.discovery.data import discopane_items, statictheme_disco_item
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.serializers import (
    DiscoveryEditorialContentSerializer,
    DiscoverySerializer,
)
from olympia.discovery.utils import get_recommendations, replace_extensions


class DiscoveryViewSet(ListModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = DiscoverySerializer

    def get_params(self):
        params = dict(self.kwargs)
        params.update(self.request.GET.iteritems())
        params = {
            param: value
            for (param, value) in params.iteritems()
            if param in amo.DISCO_API_ALLOWED_PARAMETERS
        }
        lang = params.pop('lang', None)
        if lang:
            # Need to change key to what taar expects
            params['locale'] = lang
        return params

    def get_discopane_items(self):
        if not getattr(self, 'discopane_items', None):
            params = self.get_params()
            edition = params.pop('edition', 'default')
            self.discopane_items = discopane_items.get(
                edition, discopane_items['default']
            )
            if edition == 'china':
                # No TAAR for China Edition.
                telemetry_id = None
            else:
                telemetry_id = params.pop('telemetry-client-id', None)
            if switch_is_active('disco-recommendations') and telemetry_id:
                recommendations = get_recommendations(telemetry_id, params)
                if recommendations:
                    # if we got some recommendations then replace the
                    # extensions in discopane_items with them.
                    # Leave the non-extensions (personas) alone.
                    self.discopane_items = replace_extensions(
                        self.discopane_items, recommendations
                    )
            if switch_is_active('disco-staticthemes-dev'):
                # Replace the first discopane item with a static theme to
                # enable development on frontend.
                self.discopane_items = list(self.discopane_items)
                self.discopane_items[0] = statictheme_disco_item
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


class DiscoveryItemViewSet(ListModelMixin, GenericViewSet):
    pagination_class = None
    permission_classes = []
    queryset = DiscoveryItem.objects.all().order_by('pk')
    serializer_class = DiscoveryEditorialContentSerializer

    def list(self, request, *args, **kwargs):
        # Ignore pagination (fetch all items!) but do wrap the data in a
        # 'results' property to mimic what the rest of our APIs do.
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data})
