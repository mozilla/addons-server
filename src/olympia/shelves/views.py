from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from olympia.shelves.models import Shelf
from olympia.shelves.serializers import ShelfSerializer


class ShelfViewSet(viewsets.ModelViewSet):
    format_kwarg = None
    queryset = Shelf.objects.filter(
        shelfmanagement__enabled=True).order_by('shelfmanagement__position')
    serializer_class = ShelfSerializer

    def get_shelves(self):
        return self.get_serializer(self.queryset, many=True)


class HomepageView(APIView):
    def get(self, request, format=None):
        output = {
            'info': ShelfViewSet(
                request=request).get_shelves().data,
        }
        return Response(output)
