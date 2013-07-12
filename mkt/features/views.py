from ordereddict import OrderedDict

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from mkt.constants import APP_FEATURES


class AppFeaturesList(APIView):
    authentication_classes = permission_classes = []

    def _feature(self, i, slug):
        feature = APP_FEATURES[slug.upper()]
        return (slug.lower(), {
            'name': feature['name'],
            'description': feature['description'],
            'position': i + 1
        })

    def get(self, request, *args, **kwargs):
        features = OrderedDict(self._feature(i, slug) for i, slug in
                               enumerate(APP_FEATURES.keys()))
        return Response(features, status=status.HTTP_200_OK)
