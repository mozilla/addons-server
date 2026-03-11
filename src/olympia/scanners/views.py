from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from olympia import amo
from olympia.api.authentication import JWTKeyAuthentication
from olympia.api.permissions import GroupPermission
from olympia.constants.scanners import WEBHOOK, WEBHOOK_PUSH

from .models import ScannerResult, ScannerWebhook, ScannerWebhookEvent
from .serializers import PatchScannerResultSerializer, PushScannerResultSerializer


@api_view(['POST'])
@authentication_classes([JWTKeyAuthentication])
@permission_classes([GroupPermission(amo.permissions.SCANNERS_PUSH_RESULTS)])
def push_scanner_result(request):
    webhook = ScannerWebhook.objects.filter(
        is_active=True,
        service_account=request.user,
        scannerwebhookevent__event=WEBHOOK_PUSH,
    ).first()
    if not webhook:
        raise PermissionDenied(
            'Authenticated user does not match any active scanner service account'
        )

    serializer = PushScannerResultSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    push_event = ScannerWebhookEvent.objects.get(webhook=webhook, event=WEBHOOK_PUSH)
    scanner_result = ScannerResult.objects.create(
        scanner=WEBHOOK,
        version_id=serializer.validated_data['version_id'],
        webhook_event=push_event,
        results=serializer.validated_data['results'],
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

    return Response(status=status.HTTP_204_NO_CONTENT)
