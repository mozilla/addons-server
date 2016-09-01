from django.shortcuts import get_object_or_404

from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.viewsets import GenericViewSet

from olympia import amo
from olympia.activity.serializers import ActivityLogSerializer
from olympia.addons.views import AddonChildMixin
from olympia.api.permissions import (
    AllowAddonAuthor, AllowReviewer, AllowReviewerUnlisted, AnyOf)
from olympia.devhub.models import ActivityLog
from olympia.versions.models import Version


class VersionReviewNotesViewSet(AddonChildMixin, RetrieveModelMixin,
                                ListModelMixin, GenericViewSet):
    permission_classes = [
        AnyOf(AllowAddonAuthor, AllowReviewer, AllowReviewerUnlisted),
    ]
    serializer_class = ActivityLogSerializer
    queryset = ActivityLog.objects.all()

    def get_queryset(self):
        addon = self.get_addon_object()
        version_object = get_object_or_404(
            Version.unfiltered.filter(addon=addon),
            pk=self.kwargs['version_pk'])
        alog = ActivityLog.objects.for_version(version_object)
        return alog.filter(action__in=amo.LOG_REVIEW_QUEUE_DEVELOPER)

    def get_addon_object(self):
        return super(VersionReviewNotesViewSet, self).get_addon_object(
            permission_classes=self.permission_classes)

    def check_object_permissions(self, request, obj):
        """Check object permissions against the Addon, not the ActivityLog."""
        # Just loading the add-on object should trigger permission checks.
        self.get_addon_object()
