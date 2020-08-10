from rest_framework import permissions, viewsets

from olympia.shelves.models import ShelfManagement
from olympia.shelves.serializers import HomepageSerializer


class ShelfViewSet(viewsets.ModelViewSet):
    queryset = ShelfManagement.objects.all()
    permission_classes = [
        permissions.AllowAny
    ]

    serializer_class = HomepageSerializer
