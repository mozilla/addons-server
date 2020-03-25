from rest_framework.mixins import RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet

from .models import Block
from .serializers import BlockSerializer


class BlockViewSet(RetrieveModelMixin, GenericViewSet):
    queryset = Block.objects
    serializer_class = BlockSerializer
    lookup_value_regex = '[^/]+'  # Allow '.' for email-like guids.

    def get_object(self):
        identifier = self.kwargs.pop('pk')
        self.lookup_field = 'pk' if identifier.isdigit() else 'guid'
        self.kwargs[self.lookup_field] = identifier
        return super().get_object()
