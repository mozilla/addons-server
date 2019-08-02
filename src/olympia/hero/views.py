from django.db.transaction import non_atomic_requests
from django.utils.decorators import classonlymethod

from rest_framework.mixins import ListModelMixin
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from .models import PrimaryHero
from .serializers import PrimaryHeroShelfSerializer


class ShelfViewSet(ListModelMixin, GenericViewSet):
    pagination_class = None
    format_kwarg = None

    def get_queryset(self):
        qs = super().get_queryset()
        qs = (qs.select_related('disco_addon')
                .prefetch_related(
                    'disco_addon__addon___current_version__previews'))
        return qs.filter(enabled=True)

    def get_one_random(self):
        qs = self.filter_queryset(self.get_queryset()).order_by('?')
        return self.get_serializer(instance=qs.first())

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


class HeroShelvesView(APIView):
    def get(self, request, format=None):
        output = {
            'primary': PrimaryHeroShelfViewSet(
                request=request).get_one_random().data,
        }
        return Response(output)

    @classonlymethod
    def as_view(cls, **initkwargs):
        view = super().as_view(**initkwargs)
        return non_atomic_requests(view)
