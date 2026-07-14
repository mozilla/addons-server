from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import (
    action,
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet

import olympia.core.logger
from olympia import amo
from olympia.api.authentication import JWTKeyAuthentication
from olympia.api.permissions import GroupPermission
from olympia.constants.scanners import ABORTING, SCHEDULED, WEBHOOK, WEBHOOK_PUSH

from .models import (
    ImproperScannerQueryRuleStateError,
    ScannerQueryRule,
    ScannerResult,
    ScannerWebhook,
    ScannerWebhookEvent,
)
from .serializers import (
    PatchScannerResultSerializer,
    PushScannerResultSerializer,
    ScannerQueryResultSerializer,
    ScannerQueryRuleSerializer,
)
from .tasks import run_scanner_query_rule


log = olympia.core.logger.getLogger('z.scanners.views')


@api_view(['POST'])
@authentication_classes([JWTKeyAuthentication])
@permission_classes([GroupPermission(amo.permissions.SCANNERS_PUSH_RESULTS)])
def push_scanner_result(request):
    webhook = ScannerWebhook.objects.filter(
        is_active=True,
        service_account=request.user,
        scannerwebhookevent__event=WEBHOOK_PUSH,
        scannerwebhookevent__is_active=True,
    ).first()
    if not webhook:
        raise PermissionDenied(
            'Authenticated user does not match any active scanner service account'
        )

    serializer = PushScannerResultSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    push_event = ScannerWebhookEvent.objects.get(webhook=webhook, event=WEBHOOK_PUSH)

    version_id = serializer.validated_data['version_id']
    new_rules = serializer.validated_data['results']['matchedRules']
    if (
        new_rules
        and ScannerResult.objects.filter(
            webhook_event=push_event,
            version_id=version_id,
            matched_rules__name__in=new_rules,
        ).exists()
    ):
        return Response(
            {'detail': 'Scanner result already pushed for one of the rules'},
            status=status.HTTP_409_CONFLICT,
        )

    scanner_result = ScannerResult.objects.create(
        scanner=WEBHOOK,
        version_id=version_id,
        webhook_event=push_event,
        results=serializer.validated_data['results'],
    )
    log.info(
        'Pushed new scanner result %s for version %s', scanner_result.pk, version_id
    )

    return Response({'id': scanner_result.pk}, status=status.HTTP_201_CREATED)


@api_view(['PATCH'])
@authentication_classes([JWTKeyAuthentication])
@permission_classes([GroupPermission(amo.permissions.SCANNERS_PATCH_RESULTS)])
def patch_scanner_result(request, pk=None):
    try:
        # In addition to fetching the scanner result by PK, we also ensure that
        # it is bound to a valid webhook whose service account matches the
        # authenticated user.
        scanner_result = ScannerResult.objects.get(
            pk=pk,
            scanner=WEBHOOK,
            webhook_event__webhook__service_account=request.user,
        )
    except ScannerResult.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    # Check if the scanner result has already been patched.
    if scanner_result.results is not None and 'matchedRules' in scanner_result.results:
        return Response(
            {'detail': 'Scanner result has already been updated'},
            status=status.HTTP_409_CONFLICT,
        )

    serializer = PatchScannerResultSerializer(data=request.data)
    # Return a 400 response if the data was invalid.
    serializer.is_valid(raise_exception=True)

    scanner_result.results = serializer.validated_data['results']
    # We don't pass `update_fields` because the `save()` method
    # also updates other fields (e.g. has_matches, matched_rules).
    scanner_result.save()
    log.info(
        'Patched existing scanner result %s for version %s',
        scanner_result.pk,
        scanner_result.version_id,
    )

    return Response(status=status.HTTP_204_NO_CONTENT)


class ScannerQueryRuleViewSet(ModelViewSet):
    """CRUD API for ScannerQueryRules, plus run/abort actions.

    Lets an operator programmatically author a query rule, kick off a run
    (and abort it) and iterate on the definition. The matches are exposed by
    the nested ScannerQueryResultViewSet. Only accessible with an API key
    whose user is in the appropriate admin group.

    Rules can only be edited (PUT/PATCH) while still in the NEW state; once a
    run has been scheduled the definition is frozen (enforced in the
    serializer) and a new rule should be created to iterate.
    """

    authentication_classes = [JWTKeyAuthentication]
    queryset = ScannerQueryRule.objects.all().order_by('-pk')
    serializer_class = ScannerQueryRuleSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            permission = amo.permissions.ADMIN_SCANNERS_QUERY_VIEW
        else:
            permission = amo.permissions.ADMIN_SCANNERS_QUERY_EDIT
        return [GroupPermission(permission)]

    @action(detail=True, methods=['post'])
    def run(self, request, pk=None):
        rule = self.get_object()
        try:
            # SCHEDULED is a transitional state (mirroring the admin) allowing
            # the state to be updated right away; the task switches it to
            # RUNNING once it starts being processed.
            rule.change_state_to(SCHEDULED)
        except ImproperScannerQueryRuleStateError:
            return Response(
                {
                    'detail': (
                        f'Scanner query rule could not be queued for execution '
                        f'because it was in "{rule.get_state_display()}" state.'
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        run_scanner_query_rule.delay(rule.pk)
        log.info('Scanner query rule %s has been queued for execution.', rule.pk)
        return Response(self.get_serializer(rule).data, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=['post'])
    def abort(self, request, pk=None):
        rule = self.get_object()
        try:
            rule.change_state_to(ABORTING)
        except ImproperScannerQueryRuleStateError:
            return Response(
                {
                    'detail': (
                        f'Scanner query rule could not be aborted because it '
                        f'was in "{rule.get_state_display()}" state.'
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )
        log.info('Scanner query rule %s is being aborted.', rule.pk)
        return Response(self.get_serializer(rule).data, status=status.HTTP_200_OK)


class ScannerQueryResultViewSet(ReadOnlyModelViewSet):
    """Read-only API to browse the matches (ScannerQueryResults) of a rule.

    Nested under ScannerQueryRuleViewSet, so the results are always scoped to
    a single parent rule: ``/scanner/query-rules/{query_rule_pk}/results/``."""

    authentication_classes = [JWTKeyAuthentication]
    serializer_class = ScannerQueryResultSerializer

    def get_permissions(self):
        return [GroupPermission(amo.permissions.ADMIN_SCANNERS_QUERY_VIEW)]

    def get_rule_object(self):
        if not hasattr(self, 'rule_object'):
            self.rule_object = get_object_or_404(
                ScannerQueryRule, pk=self.kwargs['query_rule_pk']
            )
        return self.rule_object

    def get_queryset(self):
        return (
            self.get_rule_object()
            .results.select_related('version__addon')
            .order_by('-pk')
        )
