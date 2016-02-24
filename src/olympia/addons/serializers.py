from rest_framework import serializers

from olympia.addons.models import Addon
from olympia.api.fields import TranslationSerializerField
from olympia.api.serializers import BaseESSerializer


class AddonSerializer(serializers.ModelSerializer):
    name = TranslationSerializerField()
    description = TranslationSerializerField()

    class Meta:
        model = Addon
        fields = ('id', 'default_locale', 'name', 'slug')


class ESAddonSerializer(BaseESSerializer, AddonSerializer):
    def fake_object(self, data):
        """Create a fake instance of Webapp and related models from ES data."""
        obj = Addon(id=data.id, slug=data.slug)

        # Set base attributes that have the same name/format in ES and in the
        # model.
        self._attach_fields(obj, data, ('created', 'default_locale', 'status'))

        # Attach translations (they require special treatment).
        self._attach_translations(obj, data, ('name', 'description'))

        return obj
