from rest_framework import fields

from amo.utils import to_language


class TranslationSerializerField(fields.WritableField):
    """
    Django-rest-framework custom serializer field for our TranslatedFields.

    - When deserializing, in `from_native`, it accepts both a string or a 
      dictionary. If a string is given, it'll be considered to be in the
      default language.

    - When serializing, its behavior depends on the parent's serializer context:

      If a request was included, and its method is 'GET', and a 'lang' parameter
      was passed, then only returns one translation (letting the TranslatedField
      figure out automatically which language to use).

      Else, just returns a dict with all translations for the given `field_name`
      on `obj`, with languages as the keys.
    """
    def __init__(self, *args, **kwargs):
        super(TranslationSerializerField, self).__init__(*args, **kwargs)
        # Default to return all translations for each field.
        self.return_all_translations = True

    def initialize(self, parent, field_name):
        super(TranslationSerializerField, self).initialize(parent, field_name)
        request = self.context.get('request', None)
        if request and request.method == 'GET' and 'lang' in request.GET:
            # A specific language was requested, we only return one translation
            # per field.
            self.return_all_translations = False

    def field_to_native(self, obj, field_name):
        field = getattr(obj, field_name)
        if not self.return_all_translations:
            return unicode(field)
        else:
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
