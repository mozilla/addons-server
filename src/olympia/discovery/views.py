from django.db.transaction import non_atomic_requests
from django.utils.decorators import classonlymethod

from rest_framework.mixins import ListModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from waffle import switch_is_active

from olympia import amo
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.serializers import (
    DiscoveryEditorialContentSerializer, DiscoverySerializer)
from olympia.discovery.utils import get_recommendations, replace_extensions


class DiscoveryViewSet(ListModelMixin, GenericViewSet):
    pagination_class = None
    permission_classes = []
    serializer_class = DiscoverySerializer

    def get_params(self):
        params = dict(self.kwargs)
        params.update(self.request.GET.iteritems())
        params = {param: value for (param, value) in params.iteritems()
                  if param in amo.DISCO_API_ALLOWED_PARAMETERS}
        lang = params.pop('lang', None)
        if lang:
            # Need to change key to what taar expects
            params['locale'] = lang
        return params

    def get_queryset(self):
        params = self.get_params()
        edition = params.pop('edition', 'default')
        position_field = 'position_china' if edition == 'china' else 'position'

        # Base queryset for editorial content.
        qs = (DiscoveryItem.objects
                           .prefetch_related('addon')
                           .filter(**{position_field + '__gt': 0})
                           .order_by(position_field))

        # Recommendations stuff, potentially replacing some/all items in
        # the queryset with recommendations if applicable.
        if edition == 'china':
            # No TAAR for China Edition.
            telemetry_id = None
        else:
            telemetry_id = params.pop('telemetry-client-id', None)
        if switch_is_active('disco-recommendations') and telemetry_id:
            recommendations = get_recommendations(
                telemetry_id, params)
            if recommendations:
                # if we got some recommendations then replace the
                # extensions in the queryset with them.
                # Leave the non-extensions (personas) alone.
                qs = replace_extensions(qs, recommendations)

        return qs

    def filter_queryset(self, qs):
        return [item for item in qs if item.addon.is_public()]

    def list(self, request, *args, **kwargs):
        # Ignore pagination (fetch all items, shouldn't be that many because
        # data is either coming from recommendation server or content selected
        # by editorial team) but do wrap the data in a `results` property to
        # mimic what the rest of our APIs do. Add a `count` to be nice with
        # clients.
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data, 'count': len(queryset)})

    @classonlymethod
    def as_view(cls, actions=None, **initkwargs):
        view = super(DiscoveryViewSet, cls).as_view(
            actions=actions, **initkwargs)
        return non_atomic_requests(view)


class DiscoveryItemViewSet(ListModelMixin, GenericViewSet):
    pagination_class = None
    permission_classes = []
    queryset = DiscoveryItem.objects.all().order_by('pk')
    serializer_class = DiscoveryEditorialContentSerializer

    def list(self, request, *args, **kwargs):
        # Ignore pagination (fetch all items!) but do wrap the data in a
        # `results` property to mimic what the rest of our APIs do.
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data})

    @classonlymethod
    def as_view(cls, actions=None, **initkwargs):
        view = super(DiscoveryItemViewSet, cls).as_view(
            actions=actions, **initkwargs)
        return non_atomic_requests(view)
