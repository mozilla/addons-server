from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.utils.encoding import smart_text
from django.utils.translation import get_language, ugettext_lazy as _

from rest_framework import fields, serializers

from olympia.amo.utils import to_language
from olympia.api.utils import is_gate_active
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

    In normal operation:
    - When deserializing, in `to_internal_value`, it accepts a dictionary only.

    - When serializing, a dict with all translations for the given
      `field_name` on `obj`, with languages as the keys.

      However, if the parent's serializer context contains a request that has
      a method 'GET', and a 'lang' parameter was passed, then only a returns
      one translation in that dict.  If the request lang is available that is
      returned, otherwise the  default locale is returned.

    If the gate 'l10n_flat_input_output' is active then:
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
        'unknown_locale': _(u'The language code {lang_code} is invalid.'),
        'no_dict': _(u'You must provide a dictionary of {lang-code:value}.')
    }

    def __init__(self, *args, **kwargs):
        self.min_length = kwargs.pop('min_length', None)
        super(TranslationSerializerField, self).__init__(*args, **kwargs)

    @property
    def flat(self):
        request = self.context.get('request', None)
        return is_gate_active(request, 'l10n_flat_input_output')

    def fetch_all_translations(self, obj, source, field):
        translations = field.__class__.objects.filter(
            id=field.id, localized_string__isnull=False)
        return {to_language(trans.locale): unicode(trans)
                for trans in translations} if translations else None

    def fetch_single_translation(self, obj, source, field, requested_language):
        return {to_language(field.locale): unicode(field)} if field else None

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
            single = self.fetch_single_translation(obj, source, field,
                                                   requested_language)
            return single.values()[0] if single and self.flat else single
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
        if not self.flat and not isinstance(value, dict):
            raise ValidationError(
                self.error_messages['no_dict']
            )
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
        if translation:
            locale, value = translation.items()[0]
            translation = Translation(localized_string=value, locale=locale)
        setattr(obj, target_name, translation)

    def fetch_all_translations(self, obj, source, field):
        return field or None

    def fetch_single_translation(self, obj, source, field, requested_language):
        translations = self.fetch_all_translations(obj, source, field) or {}
        locale = None
        value = None
        if requested_language in translations:
            locale = requested_language
            value = translations.get(requested_language)
        else:
            default_locale = getattr(
                obj, 'default_locale', settings.LANGUAGE_CODE)
            if default_locale in translations:
                locale = default_locale
                value = translations.get(default_locale)
        return {locale: value} if locale and value else None


class SplitField(fields.Field):
    """
    A field composed of two separate fields: one used for input, and another
    used for output. Most commonly used to accept a primary key for input and
    use a full serializer for output.
    Example usage:
    addon = SplitField(serializers.PrimaryKeyRelatedField(), AddonSerializer())
    """
    label = None

    def __init__(self, _input, output, **kwargs):
        self.input = _input
        self.output = output
        kwargs['required'] = _input.required
        fields.Field.__init__(self, source=_input.source, **kwargs)

    def bind(self, field_name, parent):
        fields.Field.bind(self, field_name, parent)
        self.input.bind(field_name, parent)
        self.output.bind(field_name, parent)

    def get_read_only(self):
        return self._read_only

    def set_read_only(self, val):
        self._read_only = val
        self.input.read_only = val
        self.output.read_only = val

    read_only = property(get_read_only, set_read_only)

    def get_value(self, data):
        return self.input.get_value(data)

    def to_internal_value(self, value):
        return self.input.to_internal_value(value)

    def get_attribute(self, obj):
        return self.output.get_attribute(obj)

    def to_representation(self, value):
        return self.output.to_representation(value)


class SlugOrPrimaryKeyRelatedField(serializers.RelatedField):
    """
    Combines SlugRelatedField and PrimaryKeyRelatedField. Takes a
    `render_as` argument (either "pk" or "slug") to indicate how to
    serialize.
    """
    read_only = False

    def __init__(self, *args, **kwargs):
        self.render_as = kwargs.pop('render_as', 'pk')
        if self.render_as not in ['pk', 'slug']:
            raise ValueError("'render_as' must be one of 'pk' or 'slug', "
                             "not %r" % (self.render_as,))
        self.slug_field = kwargs.pop('slug_field', 'slug')
        super(SlugOrPrimaryKeyRelatedField, self).__init__(
            *args, **kwargs)

    def to_representation(self, obj):
        if self.render_as == 'slug':
            return getattr(obj, self.slug_field)
        else:
            return obj.pk

    def to_internal_value(self, data):
        try:
            return self.queryset.get(pk=data)
        except Exception:
            try:
                return self.queryset.get(**{self.slug_field: data})
            except ObjectDoesNotExist:
                msg = (_('Invalid pk or slug "%s" - object does not exist.') %
                       smart_text(data))
                raise ValidationError(msg)
