from django.db.transaction import non_atomic_requests
from django.utils.decorators import classonlymethod

from rest_framework.mixins import ListModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from olympia.constants.promoted import PROMOTED_GROUP_CHOICES
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.serializers import (
    DiscoveryEditorialContentSerializer,
    DiscoverySerializer,
)


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
            DiscoveryItem.objects.prefetch_related(
                'addon___current_version__previews',
                'addon___current_version__file___webext_permissions',
            )
            .filter(**{position_field + '__gt': 0})
            .order_by(position_field)
        )
        return qs

    def filter_queryset(self, qs):
        return [item for item in qs if item.addon.is_public()]

    def list(self, request, *args, **kwargs):
        # Ignore pagination (fetch all items, shouldn't be that many because data is
        # coming from content selected by editorial team) but do wrap the data in a
        # `results` property to mimic what the rest of our APIs do. Add a `count` to be
        # nice with clients.
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data, 'count': len(queryset)})

    @classonlymethod
    def as_view(cls, actions=None, **initkwargs):
        view = super().as_view(actions=actions, **initkwargs)
        return non_atomic_requests(view)


class DiscoveryItemViewSet(ListModelMixin, GenericViewSet):
    pagination_class = None
    permission_classes = []
    queryset = DiscoveryItem.objects.all().select_related('addon').order_by('pk')
    serializer_class = DiscoveryEditorialContentSerializer

    def filter_queryset(self, qs):
        qs = super().filter_queryset(qs)
        if self.request.query_params.get('recommended', False) == 'true':
            qs = qs.filter(
                **{
                    'addon__promotedaddonpromotion__promoted_group__group_id': (
                        PROMOTED_GROUP_CHOICES.RECOMMENDED
                    ),
                    'addon___current_version__promoted_versions__promoted_group__group_id': PROMOTED_GROUP_CHOICES.RECOMMENDED,  # noqa
                }
            ).distinct()
        return qs

    def list(self, request, *args, **kwargs):
        # Ignore pagination (fetch all items!) but do wrap the data in a
        # `results` property to mimic what the rest of our APIs do.
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data})

    @classonlymethod
    def as_view(cls, actions=None, **initkwargs):
        view = super().as_view(actions=actions, **initkwargs)
        return non_atomic_requests(view)
