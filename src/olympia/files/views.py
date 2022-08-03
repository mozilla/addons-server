from django.core.exceptions import PermissionDenied
from django import http, shortcuts
from django.utils.crypto import constant_time_compare
from django.utils.translation import gettext

from rest_framework import exceptions, status
from rest_framework.mixins import CreateModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

import olympia.core.logger

from olympia import amo
from olympia.amo.decorators import use_primary_db
from olympia.amo.utils import HttpResponseXSendFile
from olympia.api.authentication import (
    JWTKeyAuthentication,
    SessionIDAuthentication,
)
from olympia.api.permissions import AllowOwner, APIGatePermission
from olympia.api.throttling import file_upload_throttles
from olympia.devhub import tasks as devhub_tasks
from olympia.devhub.permissions import IsSubmissionAllowedFor

from .models import FileUpload
from .serializers import FileUploadSerializer


log = olympia.core.logger.getLogger('z.addons')


@use_primary_db
def serve_file_upload(request, uuid):
    """
    This is to serve file uploads using authenticated download URLs. This is
    currently used by the "scanner" services.
    """
    upload = shortcuts.get_object_or_404(FileUpload, uuid=uuid)
    access_token = request.GET.get('access_token')

    if not access_token:
        log.error('Denying access to %s, no token.', upload.id)
        raise PermissionDenied

    if not constant_time_compare(access_token, upload.access_token):
        log.error('Denying access to %s, token invalid.', upload.id)
        raise PermissionDenied

    if not upload.path:
        log.info('Preventing access to %s, upload path is falsey.' % upload.id)
        return http.HttpResponseGone('upload path does not exist anymore')

    return HttpResponseXSendFile(
        request, upload.path, content_type='application/octet-stream'
    )


class FileUploadViewSet(CreateModelMixin, ReadOnlyModelViewSet):
    queryset = FileUpload.objects.all()
    serializer_class = FileUploadSerializer
    permission_classes = [
        APIGatePermission('addon-submission-api'),
        AllowOwner,
        IsSubmissionAllowedFor,
    ]
    authentication_classes = [
        JWTKeyAuthentication,
        SessionIDAuthentication,
    ]
    lookup_field = 'uuid'
    throttle_classes = file_upload_throttles

    def get_queryset(self):
        return super().get_queryset().filter(user=self.request.user)

    def create(self, request):
        if 'upload' in request.FILES:
            filedata = request.FILES['upload']
        else:
            raise exceptions.ValidationError(
                gettext('Missing "upload" key in multipart file data.'),
                status.HTTP_400_BAD_REQUEST,
            )
        channel = amo.CHANNEL_CHOICES_LOOKUP.get(request.POST.get('channel'))
        if not channel:
            raise exceptions.ValidationError(
                gettext('Missing "channel" arg.'),
                status.HTTP_400_BAD_REQUEST,
            )

        upload = FileUpload.from_post(
            filedata,
            filename=filedata.name,
            size=filedata.size,
            channel=channel,
            source=amo.UPLOAD_SOURCE_ADDON_API,
            user=request.user,
        )

        devhub_tasks.validate(upload, listed=(channel == amo.CHANNEL_LISTED))
        headers = self.get_success_headers({})
        data = self.get_serializer(instance=upload).data
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)
