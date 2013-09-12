from rest_framework import fields

from amo.utils import to_language


class TranslationSerializerField(fields.WritableField):
    """
    Django-rest-framework custom serializer field for our TranslatedFields.

    - When deserializing, in `from_native`, it accepts both a string or a 
      dictionary. If a string is given, it'll be considered to be in the
      default language.

    - When serializing, it returns a dict with all translations for the given
      `field_name` on `obj`, with languages as the keys.
    """
    def field_to_native(self, obj, field_name):
        field = getattr(obj, field_name)
        translations = field.__class__.objects.filter(id=field.id,
            localized_string__isnull=False)
        return dict((to_language(trans.locale), unicode(trans))
                    for trans in translations)

    def from_native(self, data):
        if isinstance(data, basestring):
            return data.strip()
        elif isinstance(data, dict):
            for key, value in data.items():
                data[key] = value.strip()
            return data
        data = super(TranslationSerializerField, self).from_native(data)
        return unicode(data)
