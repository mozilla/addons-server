from datetime import datetime

from rest_framework.serializers import ModelSerializer

from .fields import ESTranslationSerializerField, TranslationSerializerField


class BaseESSerializer(ModelSerializer):
    """
    A base deserializer that handles ElasticSearch data for a specific model.

    When deserializing, an unbound instance of the model (as defined by
    fake_object) is populated with the ES data in order to work well with
    the parent model serializer (e.g., AddonSerializer).

    """
    # In base classes add the field names we want converted to Python
    # datetime from the Elasticsearch datetime strings.
    datetime_fields = ()

    def __init__(self, *args, **kwargs):
        super(BaseESSerializer, self).__init__(*args, **kwargs)

        # Set all fields as read_only just in case.
        for field_name in self.fields:
            self.fields[field_name].read_only = True

        if getattr(self, 'context'):
            for field_name in self.fields:
                self.fields[field_name].context = self.context

    def get_fields(self):
        """
        Return all fields as normal, with one exception: replace every instance
        of TranslationSerializerField with ESTranslationSerializerField.
        """
        fields = super(BaseESSerializer, self).get_fields()
        for key, field in fields.items():
            if isinstance(field, TranslationSerializerField):
                fields[key] = ESTranslationSerializerField(source=field.source)
        return fields

    def to_internal_value(self, data):
        obj = self.fake_object(data)
        return super(BaseESSerializer, self).to_internal_value(obj)

    def fake_object(self, data):
        """
        Create a fake model instance from ES data which serializer fields will
        source from.
        """
        raise NotImplementedError

    def _attach_fields(self, obj, data, field_names):
        """Attach fields to fake instance."""
        for field_name in field_names:
            value = getattr(data, field_name, None)
            if field_name in self.datetime_fields and value:
                value = datetime.strptime(value, u'%Y-%m-%dT%H:%M:%S')
            setattr(obj, field_name, value)
        return obj

    def _attach_translations(self, obj, data, field_names):
        """Deserialize ES translation fields."""
        for field_name in field_names:
            ESTranslationSerializerField.attach_translations(
                obj, data, field_name)
        return obj
