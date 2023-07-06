from django.conf import settings
from django.db.models import CharField, Q, Value
from django.db.transaction import non_atomic_requests

from rest_framework.exceptions import ParseError
from rest_framework.generics import ListAPIView

from olympia import amo
from olympia.api.authentication import (
    JWTKeyAuthentication,
    SessionIDAuthentication,
)
from olympia.api.permissions import GroupPermission
from olympia.constants.scanners import (
    LABEL_BAD,
    LABEL_GOOD,
    SCANNERS,
    TRUE_POSITIVE,
)

from .models import ScannerResult
from .serializers import ScannerResultSerializer


class ScannerResultView(ListAPIView):
    authentication_classes = [
        JWTKeyAuthentication,
        SessionIDAuthentication,
    ]

    permission_classes = [GroupPermission(amo.permissions.ADMIN_SCANNERS_RESULTS_VIEW)]

    serializer_class = ScannerResultSerializer

    def get_queryset(self):
        label = self.request.query_params.get('label', None)
        scanner = next(
            (
                key
                for key in SCANNERS
                if SCANNERS.get(key) == self.request.query_params.get('scanner')
            ),
            None,
        )

        bad_results = ScannerResult.objects.exclude(version=None)
        good_results = ScannerResult.objects.exclude(version=None)

        if scanner:
            bad_results = bad_results.filter(scanner=scanner)
            good_results = good_results.filter(scanner=scanner)

        bad_filters = Q(state=TRUE_POSITIVE) | Q(
            version__versionlog__activity_log__action__in=(
                amo.LOG.BLOCKLIST_BLOCK_ADDED.id,
                amo.LOG.BLOCKLIST_BLOCK_EDITED.id,
                amo.LOG.BLOCKLIST_VERSION_BLOCKED.id,
            )
        )

        good_results = (
            good_results.filter(
                Q(
                    version__versionlog__activity_log__action__in=(
                        amo.LOG.CONFIRM_AUTO_APPROVED.id,
                        amo.LOG.APPROVE_VERSION.id,
                    )
                )
                & ~Q(
                    version__versionlog__activity_log__user_id=settings.TASK_USER_ID  # noqa
                )
            )
            .exclude(bad_filters)
            .distinct()
            .annotate(label=Value(LABEL_GOOD, output_field=CharField()))
            .all()
        )
        bad_results = (
            bad_results.filter(bad_filters)
            .distinct()
            .annotate(label=Value(LABEL_BAD, output_field=CharField()))
            .all()
        )

        queryset = ScannerResult.objects.none()

        if not label:
            queryset = good_results.union(bad_results)
        elif label == LABEL_GOOD:
            queryset = good_results
        elif label == LABEL_BAD:
            queryset = bad_results

        return queryset.order_by('-pk')

    def get(self, request, format=None):
        label = self.request.query_params.get('label', None)
        if label is not None and label not in [LABEL_BAD, LABEL_GOOD]:
            raise ParseError('invalid value for label')

        scanner = self.request.query_params.get('scanner', None)
        if scanner is not None and scanner not in list(SCANNERS.values()):
            raise ParseError('invalid value for scanner')

        return super().get(request, format)

    @classmethod
    def as_view(cls, **initkwargs):
        """The API is read-only so we can turn off atomic requests."""
        return non_atomic_requests(super().as_view(**initkwargs))
