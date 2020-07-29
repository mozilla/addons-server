import re

from django.db.transaction import non_atomic_requests
from django.utils.decorators import classonlymethod

from rest_framework.mixins import ListModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from waffle import switch_is_active

from olympia.constants.promoted import RECOMMENDED
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.serializers import (
    DiscoveryEditorialContentSerializer, DiscoverySerializer)
from olympia.discovery.utils import (
    get_disco_recommendations, replace_extensions)


# Permissive regexp for client IDs passed to the API, just to avoid sending
# garbage to TAAR.
VALID_CLIENT_ID = re.compile('^[a-zA-Z0-9-]+$')
EDITION_ALIASES = {
    'mozillaonline': 'china',
}


class DiscoveryViewSet(ListModelMixin, GenericViewSet):
    pagination_class = None
    permission_classes = []
    serializer_class = DiscoverySerializer

    def get_edition(self):
        edition = self.request.GET.get('edition', 'default').lower()
        return EDITION_ALIASES.get(edition, edition)

    def get_queryset(self):
        edition = self.get_edition()
        position_field = 'position_china' if edition == 'china' else 'position'

        # Base queryset for editorial content.
        qs = (
            DiscoveryItem.objects
                         .prefetch_related('addon___current_version__previews')
                         .filter(**{position_field + '__gt': 0})
                         .order_by(position_field))

        # Recommendations stuff, potentially replacing some/all items in
        # the queryset with recommendations if applicable.
        if edition == 'china':
            # No TAAR for China Edition.
            telemetry_id = None
        else:
            telemetry_id = self.request.GET.get('telemetry-client-id', None)
        if switch_is_active('disco-recommendations') and (
                telemetry_id and VALID_CLIENT_ID.match(telemetry_id)):
            overrides = list(
                DiscoveryItem.objects
                             .values_list('addon__guid', flat=True)
                             .filter(position_override__gt=0)
                             .order_by('position_override'))
            recommendations = get_disco_recommendations(
                telemetry_id, overrides)
            if recommendations:
                # if we got some recommendations then replace the
                # extensions in the queryset with them.
                # Leave the non-extensions (themes) alone.
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
    queryset = DiscoveryItem.objects.all().select_related(
        'addon').order_by('pk')
    serializer_class = DiscoveryEditorialContentSerializer

    def filter_queryset(self, qs):
        qs = super().filter_queryset(qs)
        if self.request.query_params.get('recommended', False) == 'true':
            qs = qs.filter(**{
                'addon__promotedaddon__group_id': RECOMMENDED.id,
                'addon___current_version__promoted_approvals__group_id':
                    RECOMMENDED.id})
        return qs

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
