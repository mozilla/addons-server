import os

from django import http
from django.conf import settings
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext_lazy as _

from rest_framework import exceptions, status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog, AddonLog
from olympia.activity.serializers import (
    ActivityLogSerializer,
    ActivityLogSerializerForComments,
)
from olympia.activity.tasks import process_email
from olympia.activity.utils import (
    action_from_user,
    log_and_notify,
)
from olympia.addons.views import AddonChildMixin
from olympia.amo.utils import HttpResponseXSendFile
from olympia.api.permissions import (
    AllowAddonAuthor,
    AllowListedViewerOrReviewer,
    AllowUnlistedViewerOrReviewer,
    AnyOf,
    GroupPermission,
)


class VersionReviewNotesViewSet(
    AddonChildMixin, ListModelMixin, RetrieveModelMixin, GenericViewSet
):
    permission_classes = [
        AnyOf(
            AllowAddonAuthor, AllowListedViewerOrReviewer, AllowUnlistedViewerOrReviewer
        ),
    ]
    serializer_class = ActivityLogSerializer

    def get_queryset(self):
        alog = ActivityLog.objects.for_versions(self.get_version_object())
        if not acl.is_user_any_kind_of_reviewer(self.request.user, allow_viewers=True):
            alog = alog.transform(ActivityLog.transformer_anonymize_user_for_developer)
        alog = alog.select_related('attachmentlog')
        return alog.filter(action__in=amo.LOG_REVIEW_QUEUE_DEVELOPER)

    def get_addon_object(self):
        return super().get_addon_object(
            permission_classes=self.permission_classes, georestriction_classes=[]
        )

    def get_version_object(self):
        if not hasattr(self, 'version_object'):
            addon = self.get_addon_object()
            self.version_object = get_object_or_404(
                # Fetch the version without transforms, we don't need the extra
                # data (and the addon property will be set on the version since
                # we're using the addon.versions manager).
                addon.versions(manager='unfiltered_for_relations')
                .all()
                .no_transforms(),
                pk=self.kwargs['version_pk'],
            )
        return self.version_object

    def check_object_permissions(self, request, obj):
        # Permissions checks are all done in check_permissions(), there are no
        # checks to be done for an individual activity log.
        pass

    def check_permissions(self, request):
        # Just loading the add-on object triggers permission checks, because
        # the implementation in AddonChildMixin calls AddonViewSet.get_object()
        self.get_addon_object()
        # The only thing left to test is that the Version is not deleted.
        version = self.get_version_object()
        if version.deleted and not GroupPermission(
            amo.permissions.ADDONS_VIEW_DELETED
        ).has_object_permission(request, self, version):
            raise http.Http404

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx['to_highlight'] = list(
            self.get_queryset().pending_for_developer().values_list('pk', flat=True)
        )
        return ctx

    def create(self, request, *args, **kwargs):
        version = self.get_version_object()
        serializer = ActivityLogSerializerForComments(data=request.data)
        serializer.is_valid(raise_exception=True)
        activity_object = log_and_notify(
            action_from_user(request.user, version),
            serializer.data['comments'],
            request.user,
            version,
        )
        serializer = self.get_serializer(activity_object)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


log = olympia.core.logger.getLogger('z.amo.activity')


class InboundEmailIPPermission:
    """Permit if client's IP address is allowed."""

    def has_permission(self, request, view):
        remote_ip = request.META.get('REMOTE_ADDR', '')
        allowed_ips = settings.ALLOWED_CLIENTS_EMAIL_API
        if allowed_ips and remote_ip not in allowed_ips:
            log.info(f'Request from invalid ip address [{remote_ip}]')
            return False

        return True


class RequestTooLargeException(exceptions.APIException):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    default_detail = _('Request content length is too large.')
    default_code = 'request_too_large'


@api_view(['POST'])
@authentication_classes(())
@permission_classes((InboundEmailIPPermission,))
def inbound_email(request):
    def check_secret_key(request):
        data = request.data
        secret_key = data.get('SecretKey', '')
        if not secret_key == settings.INBOUND_EMAIL_SECRET_KEY:
            log.info(f'Invalid secret key [{secret_key}] provided; [{data=}]')
            raise exceptions.PermissionDenied()

    def check_content_length(request):
        try:
            length = int(request.META.get('CONTENT_LENGTH'))
        except ValueError:
            length = 0

        max_length = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
        if length > max_length:
            log.info(f'Inbound email over content length: {length}')
            raise RequestTooLargeException(
                f'Request content length exceeds {max_length}.'
            )

    check_content_length(request)
    check_secret_key(request)

    validation_response = settings.INBOUND_EMAIL_VALIDATION_KEY
    if request.data.get('Type') == 'Validation':
        # Its just a verification check that the end-point is working.
        return Response(data=validation_response, status=status.HTTP_200_OK)

    message = request.data.get('Message', None)
    if not message:
        raise exceptions.ParseError(detail='Message not present in the POST data.')

    spam_rating = request.data.get('SpamScore', 0.0)
    process_email.apply_async((message, spam_rating))
    return Response(data=validation_response, status=status.HTTP_201_CREATED)


@non_atomic_requests
def download_attachment(request, log_id):
    """
    Download attachment for a given activity log.
    """
    log = get_object_or_404(ActivityLog, pk=log_id)
    addon = get_object_or_404(AddonLog, activity_log=log).addon
    attachmentlog = log.attachmentlog

    is_reviewer = acl.is_user_any_kind_of_reviewer(request.user, allow_viewers=True)
    is_developer = acl.check_addon_ownership(
        request.user,
        addon,
        allow_developer=True,
    )

    if not (is_reviewer or is_developer):
        raise http.Http404()

    response = HttpResponseXSendFile(request, attachmentlog.file.path)
    path = attachmentlog.file.path
    if not isinstance(path, str):
        path = path.decode('utf8')
    name = os.path.basename(path.replace('"', ''))
    disposition = f'attachment; filename="{name}"'.encode()
    response['Content-Disposition'] = disposition
    response['Access-Control-Allow-Origin'] = '*'
    return response
