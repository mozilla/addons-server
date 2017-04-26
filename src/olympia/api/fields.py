from django.conf import settings
from django.utils.translation import get_language, ugettext_lazy as _
from django.core.exceptions import ValidationError

from rest_framework import fields

from olympia.amo.utils import to_language
from olympia.translations.models import Translation


class ReverseChoiceField(fields.ChoiceField):
    """
    A ChoiceField that exposes the "human-readable" values of its choices,
    while storing the "actual" corresponding value as normal.

    This is useful when you want to expose string constants to clients while
    storing integers in the database.

    Note that the values in the `choices_dict` must be unique, since they are
    used for both serialization and de-serialization.
    """
    def __init__(self, *args, **kwargs):
        self.reversed_choices = {v: k for k, v in kwargs['choices']}
        super(ReverseChoiceField, self).__init__(*args, **kwargs)

    def to_representation(self, value):
        """
        Convert to representation by getting the "human-readable" value from
        the "actual" one.
        """
        value = self.choices.get(value, None)
        return super(ReverseChoiceField, self).to_representation(value)

    def to_internal_value(self, value):
        """
        Convert to internal value by getting the "actual" value from the
        "human-readable" one that is passed.
        """
        try:
            value = self.reversed_choices[value]
        except KeyError:
            self.fail('invalid_choice', input=value)
        return super(ReverseChoiceField, self).to_internal_value(value)


class TranslationSerializerField(fields.Field):
    """
    Django-rest-framework custom serializer field for our TranslatedFields.

    - When deserializing, in `to_internal_value`, it accepts both a string
      or a dictionary. If a string is given, it'll be considered to be in the
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
        'min_length': _(u'The field must have a length of at least {num} '
                        u'characters.'),
        'unknown_locale': _(u'The language code {lang_code} is invalid.')
    }

    def __init__(self, *args, **kwargs):
        self.min_length = kwargs.pop('min_length', None)
        super(TranslationSerializerField, self).__init__(*args, **kwargs)

    def fetch_all_translations(self, obj, source, field):
        translations = field.__class__.objects.filter(
            id=field.id, localized_string__isnull=False)
        return {to_language(trans.locale): unicode(trans)
                for trans in translations} if translations else None

    def fetch_single_translation(self, obj, source, field, requested_language):
        return unicode(field) if field else None

    def get_attribute(self, obj):
        source = self.source or self.field_name
        field = fields.get_attribute(obj, source.split('.'))

        if not field:
            return None

        requested_language = None

        request = self.context.get('request', None)
        if request and request.method == 'GET' and 'lang' in request.GET:
            requested_language = request.GET['lang']

        if requested_language:
            return self.fetch_single_translation(obj, source, field,
                                                 requested_language)
        else:
            return self.fetch_all_translations(obj, source, field)

    def to_representation(self, val):
        return val

    def to_internal_value(self, data):
        if isinstance(data, basestring):
            self.validate(data)
            return data.strip()
        elif isinstance(data, dict):
            self.validate(data)
            for key, value in data.items():
                data[key] = value and value.strip()
            return data
        return unicode(data)

    def validate(self, value):
        value_too_short = True

        if isinstance(value, basestring):
            if len(value.strip()) >= self.min_length:
                value_too_short = False
        else:
            for locale, string in value.items():
                if locale.lower() not in settings.LANGUAGES:
                    raise ValidationError(
                        self.error_messages['unknown_locale'].format(
                            lang_code=repr(locale)))
                if string and (len(string.strip()) >= self.min_length):
                    value_too_short = False
                    break

        if self.min_length and value_too_short:
            raise ValidationError(
                self.error_messages['min_length'].format(num=self.min_length))


class ESTranslationSerializerField(TranslationSerializerField):
    """
    Like TranslationSerializerField, but fetching the data from a dictionary
    built from ES data that we previously attached on the object.
    """
    suffix = '_translations'
    _source = None

    def get_source(self):
        if self._source is None:
            return None
        return self._source + self.suffix

    def set_source(self, val):
        self._source = val

    source = property(get_source, set_source)

    def attach_translations(self, obj, data, source_name, target_name=None):
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
        target_key = '%s%s' % (target_name, self.suffix)
        source_key = '%s%s' % (source_name, self.suffix)
        target_translations = {v.get('lang', ''): v.get('string', '')
                               for v in data.get(source_key, {}) or {}}
        setattr(obj, target_key, target_translations)

        # Serializer might need the single translation in the current language,
        # so fetch it and attach it directly under `target_name`. We need a
        # fake Translation() instance to prevent SQL queries from being
        # automatically made by the translations app.
        translation = self.fetch_single_translation(
            obj, target_name, target_translations, get_language())
        setattr(obj, target_name, Translation(localized_string=translation))

    def fetch_all_translations(self, obj, source, field):
        return field or None

    def fetch_single_translation(self, obj, source, field, requested_language):
        translations = self.fetch_all_translations(obj, source, field) or {}
        return (translations.get(requested_language) or
                translations.get(getattr(obj, 'default_locale', None)) or
                translations.get(getattr(obj, 'default_language', None)) or
                translations.get(settings.LANGUAGE_CODE) or None)
