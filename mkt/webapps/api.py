from django.core.validators import ValidationError

from rest_framework import fields, serializers

from mkt.api.base import CompatRelatedField
from mkt.constants.features import FeatureProfile
from mkt.webapps.models import AppFeatures, Webapp


class AppFeaturesSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppFeatures

    def to_native(self, obj):
        ret = super(AppFeaturesSerializer, self).to_native(obj)
        profile = FeatureProfile.from_signature(obj.to_signature())
        ret['required'] = profile.to_list()
        return ret


class AppSerializer(serializers.ModelSerializer):
    """
    A wacky serializer type that unserializes PK numbers or slugs and
    serializes (some) app fields.
    """
    resource_uri = CompatRelatedField(
        view_name='api_dispatch_detail', read_only=True,
        tastypie={'resource_name': 'app',
                  'api_name': 'apps'},
        source='*')
    id = fields.IntegerField(source='pk')

    class Meta:
        model = Webapp
        fields = ('name', 'resource_uri', 'id')
