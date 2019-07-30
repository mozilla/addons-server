from rest_framework.mixins import ListModelMixin
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from .models import PrimaryHero, SecondaryHero
from .serializers import (
    PrimaryHeroShelfSerializer, SecondaryHeroShelfSerializer)


class ShelfViewSet(ListModelMixin, GenericViewSet):
    pagination_class = None
    format_kwarg = None

    def get_queryset(self):
        return super().get_queryset().filter(enabled=True)

    def get_one_random(self):
        qs = self.filter_queryset(self.get_queryset()).order_by('?')
        return self.get_serializer(instance=qs.first())

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        # Simulate pagination-like results, without actual pagination.
        return Response({'results': serializer.data})


class PrimaryHeroShelfViewSet(ShelfViewSet):
    queryset = PrimaryHero.objects
    serializer_class = PrimaryHeroShelfSerializer


class SecondaryHeroShelfViewSet(ShelfViewSet):
    queryset = SecondaryHero.objects
    serializer_class = SecondaryHeroShelfSerializer


class HeroShelvesView(APIView):
    def get(self, request, format=None):
        output = {
            'primary': PrimaryHeroShelfViewSet(
                request=request).get_one_random().data,
            'secondary': SecondaryHeroShelfViewSet(
                request=request).get_one_random().data,
        }
        return Response(output)
