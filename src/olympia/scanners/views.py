import waffle

from django.conf import settings
from django.db.models import CharField, Value
from django.db.transaction import non_atomic_requests
from django.http import Http404
from rest_framework.generics import ListAPIView

from olympia import amo
from olympia.constants.scanners import TRUE_POSITIVE, LABEL_BAD, LABEL_GOOD
from olympia.api.permissions import GroupPermission

from .models import ScannerResult
from .serializers import ScannerResultSerializer


class ScannerResultViewSet(ListAPIView):
    permission_classes = [
        GroupPermission(amo.permissions.ADMIN_SCANNERS_RESULTS_VIEW)
    ]

    serializer_class = ScannerResultSerializer

    def get_queryset(self):
        good_results = (
            ScannerResult.objects.exclude(version=None)
            .exclude(
                version__versionlog__activity_log__user_id=settings.TASK_USER_ID  # noqa
            )
            .filter(
                version__versionlog__activity_log__action__in=(
                    amo.LOG.CONFIRM_AUTO_APPROVED.id,
                    amo.LOG.APPROVE_VERSION.id,
                )
            )
            .annotate(label=Value(LABEL_GOOD, output_field=CharField()))
            .all()
        )
        bad_results = (
            ScannerResult.objects.exclude(version=None)
            .filter(state=TRUE_POSITIVE)
            .annotate(label=Value(LABEL_BAD, output_field=CharField()))
            .all()
        )
        return good_results.union(bad_results).order_by('-created')

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
