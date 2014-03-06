from ordereddict import OrderedDict

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from mkt.api.base import CORSMixin
from mkt.constants.features import APP_FEATURES, FeatureProfile


class AppFeaturesList(CORSMixin, APIView):
    authentication_classes = permission_classes = []
    cors_allowed_methods = ['get']

    def _feature(self, i, slug):
        feature = APP_FEATURES[slug.upper()]
        data = {
            'name': feature['name'],
            'description': feature['description'],
            'position': i + 1,
        }
        if self.profile:
            data['present'] = self.profile.get(slug.lower(), False)
        return (slug.lower(), data)

    def get(self, request, *args, **kwargs):
        if 'pro' in request.GET:
            self.profile = FeatureProfile.from_signature(request.GET['pro'])
        else:
            self.profile = None
        features = OrderedDict(self._feature(i, slug) for i, slug in
                               enumerate(APP_FEATURES.keys()))
        return Response(features, status=status.HTTP_200_OK)
