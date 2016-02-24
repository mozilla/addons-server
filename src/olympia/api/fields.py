from django.conf import settings
from django.utils.translation import ugettext_lazy as _lazy

from rest_framework import fields
from rest_framework import serializers

from olympia.amo.utils import to_language


class TranslationSerializerField(fields.WritableField):
    """
    Django-rest-framework custom serializer field for our TranslatedFields.

    - When deserializing, in `from_native`, it accepts both a string or a
      dictionary. If a string is given, it'll be considered to be in the
      default language.

    - When serializing, its behavior depends on the parent's serializer
      context:

      If a request was included, and its method is 'GET', and a 'lang'
      parameter was passed, then only returns one translation (letting the
      TranslatedField figure out automatically which language to use).

      Else, just returns a dict with all translations for the given
      `field_name` on `obj`, with languages as the keys.
    """
    default_error_messages = {
        'min_length': _lazy(u'The field must have a length of at least {num} '
                            'characters.'),
        'unknown_locale': _lazy(u'The language code {lang_code} is invalid.')
    }

    def __init__(self, *args, **kwargs):
        self.min_length = kwargs.pop('min_length', None)

        super(TranslationSerializerField, self).__init__(*args, **kwargs)
        # Default to return all translations for each field.
        self.requested_language = None

    def initialize(self, parent, field_name):
        super(TranslationSerializerField, self).initialize(parent, field_name)
        request = self.context.get('request', None)
        if request and request.method == 'GET' and 'lang' in request.GET:
            # A specific language was requested, we will only return one
            # translation per field.
            self.requested_language = request.GET['lang']

    def fetch_all_translations(self, obj, source, field):
        translations = field.__class__.objects.filter(
            id=field.id, localized_string__isnull=False)
        return dict((to_language(trans.locale), unicode(trans))
                    for trans in translations) if translations else None

    def fetch_single_translation(self, obj, source, field):
        return unicode(field) if field else None

    def field_to_native(self, obj, field_name):
        source = self.source or field_name
        value = obj
        for component in source.split('.'):
            value = fields.get_component(value, component)
            if value is None:
                break

        field = value
        if field is None:
            return None
        if self.requested_language:
            return self.fetch_single_translation(obj, source, field)
        else:
            return self.fetch_all_translations(obj, source, field)

    def from_native(self, data):
        if isinstance(data, basestring):
            return data.strip()
        elif isinstance(data, dict):
            for key, value in data.items():
                data[key] = value and value.strip()
            return data
        data = super(TranslationSerializerField, self).from_native(data)
        return unicode(data)

    def validate(self, value):
        super(TranslationSerializerField, self).validate(value)
        value_too_short = True

        if isinstance(value, basestring):
            if len(value.strip()) >= self.min_length:
                value_too_short = False
        else:
            for locale, string in value.items():
                if locale.lower() not in settings.LANGUAGES:
                    raise serializers.ValidationError(
                        self.error_messages['unknown_locale'].format(
                            lang_code=repr(locale)))
                if string and (len(string.strip()) >= self.min_length):
                    value_too_short = False
                    break

        if self.min_length and value_too_short:
            raise serializers.ValidationError(
                self.error_messages['min_length'].format(num=self.min_length))


class ESTranslationSerializerField(TranslationSerializerField):
    """
    Like TranslationSerializerField, but fetching the data from a dictionary
    built from ES data that we previously attached on the object.
    """
    suffix = '_translations'

    def __init__(self, *args, **kwargs):
        if kwargs.get('source'):
            kwargs['source'] = '%s%s' % (kwargs['source'], self.suffix)
        super(ESTranslationSerializerField, self).__init__(*args, **kwargs)

    @classmethod
    def attach_translations(cls, obj, data, source_name, target_name=None):
        """
        Look for the translation of `source_name` in `data` and create a dict
        with all translations for this field (which will look like
        {'en-US': 'mytranslation'}) and attach it to a property on `obj`.
        The property name is built with `target_name` and `cls.suffix`. If
        `target_name` is None, `source_name` is used instead.

        The suffix is necessary for two reasons:
        1) The translations app won't let us set the dict on the real field
           without making db queries
        2) This also exactly matches how we store translations in ES, so we can
           directly fetch the translations in the data passed to this method.
        """
        if target_name is None:
            target_name = source_name
        target_key = '%s%s' % (target_name, cls.suffix)
        source_key = '%s%s' % (source_name, cls.suffix)
        setattr(obj, target_key,
                dict((getattr(v, 'lang', ''), getattr(v, 'string', ''))
                     for v in getattr(data, source_key, {}) or {}))

    def fetch_all_translations(self, obj, source, field):
        return field or None

    def fetch_single_translation(self, obj, source, field):
        translations = self.fetch_all_translations(obj, source, field) or {}

        return (translations.get(self.requested_language) or
                translations.get(getattr(obj, 'default_locale', None)) or
                translations.get(settings.LANGUAGE_CODE) or None)

    def field_to_native(self, obj, field_name):
        if field_name:
            field_name = '%s%s' % (field_name, self.suffix)
        return super(ESTranslationSerializerField, self).field_to_native(
            obj, field_name)
