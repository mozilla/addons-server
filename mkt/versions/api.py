from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import ParseError

import amo
from mkt.api.authorization import AllowAppOwner
from mkt.api.base import CompatRelatedField
from mkt.constants import APP_FEATURES
from mkt.features.api import AppFeaturesSerializer
from versions.models import Version


class VersionSerializer(serializers.ModelSerializer):
    addon = CompatRelatedField(view_name='api_dispatch_detail', read_only=True,
                               tastypie={'resource_name': 'app',
                                         'api_name': 'apps'})

    class Meta:
        model = Version
        fields = ('addon', '_developer_name', 'releasenotes', 'version')
        depth = 0
        field_rename = {
            '_developer_name': 'developer_name',
            'releasenotes': 'release_notes',
            'addon': 'app'
        }

    def to_native(self, obj):
        native = super(VersionSerializer, self).to_native(obj)

        # Add non-field data to the response.
        native.update({
            'features': AppFeaturesSerializer().to_native(obj.features),
            'is_current_version': obj.addon.current_version == obj,
            'releasenotes': (unicode(obj.releasenotes) if obj.releasenotes else
                             None),
        })

        # Remap fields to friendlier, more backwards-compatible names.
        for old, new in self.Meta.field_rename.items():
            native[new] = native[old]
            del native[old]

        return native


class VersionViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                     viewsets.GenericViewSet):
    queryset = Version.objects.exclude(addon__status=amo.STATUS_DELETED)
    serializer_class = VersionSerializer
    authorization_classes = []
    permission_classes = []

    def update(self, request, *args, **kwargs):
        """
        Allow a version's features to be updated.
        """
        obj = self.get_object()

        # Deny access to users who are not owners of this app.
        if not AllowAppOwner().has_object_permission(request, self, obj.addon):
            self.permission_denied(request)

        # Update features if they are provided.
        if 'features' in request.DATA:

            # Raise an exception if any invalid features are passed.
            invalid = [f for f in request.DATA['features'] if f.upper() not in
                       APP_FEATURES.keys()]
            if any(invalid):
                raise ParseError('Invalid feature(s): %s' % ', '.join(invalid))

            # Update the value of each feature (note: a feature not present in
            # the form data is assumed to be False)
            data = {}
            for key, name in APP_FEATURES.items():
                field_name = 'has_' + key.lower()
                data[field_name] = key.lower() in request.DATA['features']
            obj.features.update(**data)

            del request.DATA['features']

        return super(VersionViewSet, self).update(request, *args, **kwargs)
