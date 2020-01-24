import waffle

from django.db.transaction import non_atomic_requests
from django.http import Http404
from rest_framework.generics import ListAPIView

from olympia import amo
from olympia.api.permissions import GroupPermission

from .models import ScannerResult
from .serializers import ScannerResultSerializer


class ScannerResultViewSet(ListAPIView):
    permission_classes = [
        GroupPermission(amo.permissions.ADMIN_SCANNERS_RESULTS_VIEW)
    ]

    queryset = ScannerResult.objects.all()
    serializer_class = ScannerResultSerializer

    def get(self, request, format=None):
        if not waffle.switch_is_active('enable-scanner-results-api'):
            raise Http404
        return super().get(request, format)

    @classmethod
    def as_view(cls, **initkwargs):
        """The API is read-only so we can turn off atomic requests."""
        return non_atomic_requests(
            super(ScannerResultViewSet, cls).as_view(**initkwargs)
        )
