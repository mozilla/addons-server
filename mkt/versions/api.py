from rest_framework import mixins, serializers, viewsets
from rest_framework.exceptions import ParseError

import amo
from mkt.api.authorization import (AllowAppOwner, AllowReadOnly, AnyOf,
                                   GroupPermission)
from mkt.constants import APP_FEATURES
from mkt.features.api import AppFeaturesSerializer
from versions.models import Version


class SimpleVersionSerializer(serializers.ModelSerializer):
    resource_uri = serializers.HyperlinkedIdentityField(
        view_name='version-detail')

    class Meta:
        model = Version
        fields = ('version', 'resource_uri')


class VersionSerializer(serializers.ModelSerializer):
    addon = serializers.HyperlinkedRelatedField(view_name='app-detail',
                                                read_only=True)

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
    queryset = Version.objects.filter(
        addon__type=amo.ADDON_WEBAPP).exclude(addon__status=amo.STATUS_DELETED)
    serializer_class = VersionSerializer
    authorization_classes = []
    permission_classes = [AnyOf(AllowAppOwner,
                                GroupPermission('Apps', 'Review'),
                                AllowReadOnly)]

    def update(self, request, *args, **kwargs):
        """
        Allow a version's features to be updated.
        """
        obj = self.get_object()

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
