from rest_framework import viewsets

from olympia.shelves.models import Shelf
from olympia.shelves.serializers import ShelfSerializer


class ShelfViewSet(viewsets.ModelViewSet):
    queryset = Shelf.objects.filter(
        shelfmanagement__enabled=True).order_by('shelfmanagement__position')
    permission_classes = []

    serializer_class = ShelfSerializer
