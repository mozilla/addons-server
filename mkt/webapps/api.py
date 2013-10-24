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

    def field_from_native(self, data, files, field_name, into):
        try:
            value = data[field_name]
        except KeyError:
            if self.required:
                raise ValidationError(self.error_messages['required'])
            return
        if value in (None, ''):
            obj = None
        else:
            try:
                try:
                    pk = int(value)
                    obj = Webapp.objects.get(pk=pk)
                except ValueError:
                    obj = Webapp.objects.get(app_slug=value)
            except Webapp.DoesNotExist:
                msg = "Invalid pk '%s' - object does not exist." % (data,)
                raise ValidationError(msg)
        into[self.source or field_name] = obj
