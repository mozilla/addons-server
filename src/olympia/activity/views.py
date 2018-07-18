import json

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext

from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.exceptions import ParseError
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.activity.serializers import ActivityLogSerializer
from olympia.activity.tasks import process_email
from olympia.activity.utils import (
    action_from_user,
    filter_queryset_to_pending_replies,
    log_and_notify,
)
from olympia.addons.views import AddonChildMixin
from olympia.api.permissions import (
    AllowAddonAuthor,
    AllowReviewer,
    AllowReviewerUnlisted,
    AnyOf,
)
from olympia.versions.models import Version


class VersionReviewNotesViewSet(
    AddonChildMixin, ListModelMixin, RetrieveModelMixin, GenericViewSet
):
    permission_classes = [
        AnyOf(AllowAddonAuthor, AllowReviewer, AllowReviewerUnlisted)
    ]
    serializer_class = ActivityLogSerializer

    def get_queryset(self):
        alog = ActivityLog.objects.for_version(self.get_version_object())
        return alog.filter(action__in=amo.LOG_REVIEW_QUEUE_DEVELOPER)

    def get_addon_object(self):
        return super(VersionReviewNotesViewSet, self).get_addon_object(
            permission_classes=self.permission_classes
        )

    def get_version_object(self):
        return get_object_or_404(
            Version.unfiltered.filter(addon=self.get_addon_object()),
            pk=self.kwargs['version_pk'],
        )

    def check_object_permissions(self, request, obj):
        """Check object permissions against the Addon, not the ActivityLog."""
        # Just loading the add-on object triggers permission checks, because
        # the implementation in AddonChildMixin calls AddonViewSet.get_object()
        self.get_addon_object()

    def get_serializer_context(self):
        ctx = super(VersionReviewNotesViewSet, self).get_serializer_context()
        ctx['to_highlight'] = filter_queryset_to_pending_replies(
            self.get_queryset()
        )
        return ctx

    def create(self, request, *args, **kwargs):
        version = self.get_version_object()
        latest_version = version.addon.find_latest_version(
            channel=version.channel, exclude=()
        )
        if version != latest_version:
            raise ParseError(
                ugettext(
                    'Only latest versions of addons can have notes added.'
                )
            )
        activity_object = log_and_notify(
            action_from_user(request.user, version),
            request.data['comments'],
            request.user,
            version,
        )
        serializer = self.get_serializer(activity_object)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


log = olympia.core.logger.getLogger('z.amo.activity')


class EmailCreationPermission(object):
    """Permit if client's IP address is allowed."""

    def has_permission(self, request, view):
        try:
            # request.data isn't available at this point.
            data = json.loads(request.body)
        except ValueError:
            # Verification checks don't send JSON, but do send the key as POST.
            data = request.POST

        secret_key = data.get('SecretKey', '')
        if not secret_key == settings.INBOUND_EMAIL_SECRET_KEY:
            log.info(
                'Invalid secret key [%s] provided; data [%s]'
                % (secret_key, data)
            )
            return False

        remote_ip = request.META.get('REMOTE_ADDR', '')
        allowed_ips = settings.ALLOWED_CLIENTS_EMAIL_API
        if allowed_ips and remote_ip not in allowed_ips:
            log.info('Request from invalid ip address [%s]' % (remote_ip,))
            return False

        return True


@api_view(['POST'])
@authentication_classes(())
@permission_classes((EmailCreationPermission,))
def inbound_email(request):
    validation_response = settings.INBOUND_EMAIL_VALIDATION_KEY
    if request.data.get('Type', '') == 'Validation':
        # Its just a verification check that the end-point is working.
        return Response(data=validation_response, status=status.HTTP_200_OK)

    message = request.data.get('Message', None)
    if not message:
        raise ParseError(detail='Message not present in the POST data.')

    process_email.apply_async((message,))
    return Response(data=validation_response, status=status.HTTP_201_CREATED)
