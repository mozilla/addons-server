from rest_framework import fields


class TranslationSerializerField(fields.WritableField):
    """
    Django-rest-framework custom serializer field for our TranslatedFields. It
    follows closely the way TranslationDescriptor works, which means:

    - When deserializing, in `from_native`, it accepts both a string or a 
      dictionary.
    - When serializing, it behaves like a regular charfield, simply returning
      the unicode version of the field (which corresponds to the translation 
      found for the currently used language)
    """
    def field_to_native(self, obj, field_name):
        return unicode(getattr(obj, field_name))

    def from_native(self, value):
        if isinstance(value, (basestring, dict)):
            return value
        value = super(TranslationSerializerField, self).from_native(value)
        return unicode(value)
