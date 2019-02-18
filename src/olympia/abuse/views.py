from django.http import Http404

from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.mixins import CreateModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from olympia.abuse.models import AbuseReport
from olympia.abuse.serializers import (
    AddonAbuseReportSerializer, UserAbuseReportSerializer)
from olympia.accounts.views import AccountViewSet
from olympia.addons.views import AddonViewSet
from olympia.api.throttling import GranularUserRateThrottle


class AbuseThrottle(GranularUserRateThrottle):
    rate = '20/day'
    scope = 'user_abuse'


class AddonAbuseViewSet(CreateModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = AddonAbuseReportSerializer
    throttle_classes = (AbuseThrottle,)

    def get_addon_viewset(self):
        if hasattr(self, 'addon_viewset'):
            return self.addon_viewset

        if 'addon_pk' not in self.kwargs:
            self.kwargs['addon_pk'] = (
                self.request.data.get('addon') or
                self.request.GET.get('addon'))
        self.addon_viewset = AddonViewSet(
            request=self.request, permission_classes=[],
            kwargs={'pk': self.kwargs['addon_pk']})
        return self.addon_viewset

    def get_addon_object(self):
        if hasattr(self, 'addon_object'):
            return self.addon_object

        self.addon_object = self.get_addon_viewset().get_object()
        return self.addon_object

    def get_guid(self):
        # See if the addon input is guid-like, if so set guid.
        if self.get_addon_viewset().get_lookup_field(
                self.kwargs['addon_pk']) == 'guid':
            guid = self.kwargs['addon_pk']
            try:
                # But see if it's also in our database.
                self.get_addon_object()
            except Http404:
                # If it isn't, that's okay, we have a guid.  Setting
                # addon_object=None here means get_addon_object won't raise 404
                self.addon_object = None
            return guid
        return None


class UserAbuseViewSet(CreateModelMixin, GenericViewSet):
    permission_classes = []
    serializer_class = UserAbuseReportSerializer
    throttle_classes = (AbuseThrottle,)

    def get_user_object(self):
        if hasattr(self, 'user_object'):
            return self.user_object

        if 'user_pk' not in self.kwargs:
            self.kwargs['user_pk'] = (
                self.request.data.get('user') or
                self.request.GET.get('user'))

        return AccountViewSet(
            request=self.request, permission_classes=[],
            kwargs={'pk': self.kwargs['user_pk']}).get_object()
