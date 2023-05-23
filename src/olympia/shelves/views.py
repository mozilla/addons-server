from django.db.transaction import non_atomic_requests
from django.utils.decorators import classonlymethod

from rest_framework import mixins, viewsets
from rest_framework.response import Response

from olympia.hero.views import PrimaryHeroShelfViewSet, SecondaryHeroShelfViewSet

from .models import Shelf
from .serializers import ShelfEditorialSerializer, ShelfSerializer


class ShelfViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Shelf.objects.filter(enabled=True).order_by('position')
    permission_classes = []
    serializer_class = ShelfSerializer
    pagination_class = None

    def list(self, request, *args, **kwargs):
        results = super().list(request, *args, **kwargs).data
        return Response(
            {
                'results': results,
                'primary': PrimaryHeroShelfViewSet(
                    request=request
                ).get_one_random_data(),
                'secondary': SecondaryHeroShelfViewSet(
                    request=request
                ).get_one_random_data(),
            }
        )

    @classonlymethod
    def as_view(cls, *args, **initkwargs):
        view = super().as_view(*args, **initkwargs)
        return non_atomic_requests(view)


class EditorialShelfViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Shelf.objects
    permission_classes = []
    serializer_class = ShelfEditorialSerializer
    pagination_class = None

    def list(self, request, *args, **kwargs):
        results = super().list(request, *args, **kwargs).data
        return Response(
            {
                'results': results,
            }
        )

    @classonlymethod
    def as_view(cls, *args, **initkwargs):
        view = super().as_view(*args, **initkwargs)
        return non_atomic_requests(view)
