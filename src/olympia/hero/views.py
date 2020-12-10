from django.db.models import Q
from django.db.transaction import non_atomic_requests
from django.utils.decorators import classonlymethod

from rest_framework.mixins import ListModelMixin
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from olympia import amo

from .models import PrimaryHero, SecondaryHero
from .serializers import PrimaryHeroShelfSerializer, SecondaryHeroShelfSerializer


class ShelfViewSet(ListModelMixin, GenericViewSet):
    pagination_class = None
    format_kwarg = None

    @property
    def is_all(self):
        return self.request.GET.get('all', '').lower() == 'true'

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.is_all:
            qs = qs.filter(enabled=True)
        return qs

    def get_one_random_data(self):
        qs = self.filter_queryset(self.get_queryset()).order_by('?')
        shelf = qs.first()
        return self.get_serializer(instance=shelf).data if shelf else None

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        # Simulate pagination-like results, without actual pagination.
        return Response({'results': serializer.data})

    @classonlymethod
    def as_view(cls, actions=None, **initkwargs):
        view = super().as_view(actions=actions, **initkwargs)
        return non_atomic_requests(view)


class PrimaryHeroShelfViewSet(ShelfViewSet):
    queryset = PrimaryHero.objects
    serializer_class = PrimaryHeroShelfSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.is_all:
            qs = qs.filter(
                Q(promoted_addon__addon__status=amo.STATUS_APPROVED)
                | Q(
                    is_external=True,
                    promoted_addon__addon__status__in=(
                        amo.VALID_ADDON_STATUSES + (amo.STATUS_NULL,)
                    ),
                ),
                promoted_addon__addon__disabled_by_user=False,
            )
        qs = qs.select_related('promoted_addon', 'select_image').prefetch_related(
            'promoted_addon__addon___current_version__previews'
        )
        return qs


class SecondaryHeroShelfViewSet(ShelfViewSet):
    queryset = SecondaryHero.objects
    serializer_class = SecondaryHeroShelfSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.prefetch_related('modules')
        return qs


class HeroShelvesView(APIView):
    def get(self, request, format=None):
        output = {
            'primary': PrimaryHeroShelfViewSet(request=request).get_one_random_data(),
            'secondary': SecondaryHeroShelfViewSet(
                request=request
            ).get_one_random_data(),
        }
        return Response(output)

    @classonlymethod
    def as_view(cls, **initkwargs):
        view = super().as_view(**initkwargs)
        return non_atomic_requests(view)
