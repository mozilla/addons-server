from rest_framework import serializers

from mkt.constants.features import FeatureProfile
from mkt.webapps.models import AppFeatures


class AppFeaturesSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppFeatures

    def to_native(self, obj):
        ret = super(AppFeaturesSerializer, self).to_native(obj)
        profile = FeatureProfile.from_signature(obj.to_signature())
        ret['required'] = profile.to_list()
        return ret
