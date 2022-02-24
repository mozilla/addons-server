import re

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.validators import RegexValidator
from django.utils.encoding import smart_str
from django.utils.translation import get_language, gettext, gettext_lazy as _, override

from rest_framework import exceptions, fields, serializers

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import get_outgoing_url
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
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        """
        Convert to representation by getting the "human-readable" value from
        the "actual" one.
        """
        value = self.choices.get(value, None)
        return super().to_representation(value)

    def to_internal_value(self, value):
        """
        Convert to internal value by getting the "actual" value from the
        "human-readable" one that is passed.
        """
        try:
            value = self.reversed_choices[value]
        except KeyError:
            self.fail('invalid_choice', input=value)
        return super().to_internal_value(value)


class TranslationSerializerField(fields.CharField):
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
        **fields.CharField.default_error_messages,
        'unknown_locale': _('The language code {lang_code} is invalid.'),
        'no_dict': _('You must provide an object of {lang-code:value}.'),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **{'allow_null': True, **kwargs})

    @property
    def flat(self):
        request = self.context.get('request', None)
        return is_gate_active(request, 'l10n_flat_input_output')

    def get_requested_language(self):
        request = self.context.get('request', None)
        if request and request.method == 'GET' and 'lang' in request.GET:
            return request.GET['lang']
        else:
            return None

    def fetch_all_translations(self, obj, source, field):
        # this property is set by amo.utils.attach_trans_dict
        if trans_dict := getattr(obj, 'translations', None):
            translations = trans_dict.get(field.id, [])
            return {to_language(locale): value for (locale, value) in translations}
        else:
            translations = field.__class__.objects.filter(
                id=field.id, localized_string__isnull=False
            )
            return {to_language(trans.locale): str(trans) for trans in translations}

    def _format_single_translation_response(self, value, lang, requested_lang):
        if not value or not lang:
            return None
        if lang == requested_lang:
            return {lang: value}
        else:
            return {lang: value, requested_lang: None, '_default': lang}

    def fetch_single_translation(self, obj, source, field, requested_language):
        return self._format_single_translation_response(
            str(field) if field else field,
            to_language(field.locale),
            to_language(requested_language),
        )

    def get_attribute(self, obj):
        source = self.source or self.field_name
        try:
            field = fields.get_attribute(obj, source.split('.'))
        except AttributeError:
            field = None

        if not field:
            return None

        requested_language = self.get_requested_language()

        if requested_language:
            single = self.fetch_single_translation(
                obj, source, field, requested_language
            )
            return list(single.values())[0] if single and self.flat else single
        else:
            return self.fetch_all_translations(obj, source, field)

    def to_representation(self, val):
        return val

    def run_validation(self, data=fields.empty):
        if data != fields.empty and not self.flat and not isinstance(data, dict):
            raise exceptions.ValidationError(self.error_messages['no_dict'])

        if isinstance(data, dict):
            for locale, value in data.items():
                if locale.lower() not in settings.LANGUAGE_URL_MAP:
                    raise exceptions.ValidationError(
                        self.error_messages['unknown_locale'].format(
                            lang_code=repr(locale)
                        )
                    )
                data[locale] = super().run_validation(value)
            return data

        return super().run_validation(data)


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
        target_key = f'{target_name}{self.suffix}'
        source_key = f'{source_name}{self.suffix}'
        target_translations = {
            v.get('lang', ''): v.get('string', '')
            for v in data.get(source_key, {}) or {}
        }
        setattr(obj, target_key, target_translations)

        # Serializer might need the single translation in the current language,
        # so fetch it and attach it directly under `target_name`. We need a
        # fake Translation() instance to prevent SQL queries from being
        # automatically made by the translations app.
        translation = self.fetch_single_translation(
            obj, target_name, target_translations, get_language()
        )
        if translation:
            locale, value = list(translation.items())[0]
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
            default_locale = getattr(obj, 'default_locale', settings.LANGUAGE_CODE)
            if default_locale in translations:
                locale = default_locale
                value = translations.get(default_locale)
        return self._format_single_translation_response(
            value, locale, requested_language
        )


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
            raise ValueError(
                "'render_as' must be one of 'pk' or 'slug', "
                'not %r' % (self.render_as,)
            )
        self.slug_field = kwargs.pop('slug_field', 'slug')
        super().__init__(*args, **kwargs)

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
                msg = _('Invalid pk or slug "%s" - object does not exist.') % smart_str(
                    data
                )
                raise exceptions.ValidationError(msg)


class OutgoingSerializerMixin:
    """
    URL fields, but wrapped with our outgoing server.
    """

    def __init__(self, **kwargs):
        # By default prevent internal urls from being specified
        allow_internal = kwargs.pop('allow_internal', False)
        super().__init__(**kwargs)
        if not allow_internal:
            validator = RegexValidator(
                regex=r'%s' % re.escape(settings.EXTERNAL_SITE_URL),
                message=_(
                    'This field can only be used to link to external websites.'
                    ' URLs on %(domain)s are not allowed.',
                )
                % {'domain': settings.EXTERNAL_SITE_URL},
                code='no_amo_url',
                inverse_match=True,
            )
            self.validators.append(validator)

    def to_representation(self, value):
        data = super().to_representation(value)
        request = self.context.get('request', None)

        if request and is_gate_active(request, 'wrap-outgoing-parameter'):
            if data and 'wrap_outgoing_links' in request.GET:
                if isinstance(data, str):
                    return get_outgoing_url(data)
                elif isinstance(data, dict):
                    return {
                        key: get_outgoing_url(value) if value else None
                        for key, value in data.items()
                    }
            # None or empty string... don't bother.
            return data

        if not data:
            return None
        if isinstance(data, dict):
            outgoing = {
                key: value
                if key == '_default'
                else get_outgoing_url(value)
                if value
                else None
                for key, value in data.items()
            }
        else:
            outgoing = get_outgoing_url(str(data))
        return {'url': data, 'outgoing': outgoing}


class URLTranslationField(serializers.URLField, TranslationSerializerField):
    pass


class EmailTranslationField(serializers.EmailField, TranslationSerializerField):
    pass


class OutgoingURLField(OutgoingSerializerMixin, serializers.URLField):
    pass


class OutgoingURLTranslationField(OutgoingSerializerMixin, URLTranslationField):
    pass


class OutgoingURLESTranslationField(
    OutgoingSerializerMixin, ESTranslationSerializerField
):
    pass


class AbsoluteOutgoingURLField(OutgoingURLField):
    def __init__(self, **kwargs):
        # Switch the default to allow_internal=True, because absolutify is only needed
        # for internal urls so using this class means they're possible values.
        kwargs['allow_internal'] = kwargs.get('allow_internal', True)
        super().__init__(**kwargs)

    def to_representation(self, obj):
        return super().to_representation(absolutify(obj) if obj else obj)


class GetTextTranslationSerializerField(TranslationSerializerField):
    """A TranslationSerializerField that gets it's translations from .po files via
    gettext rather than the database with TranslatedField."""

    def _fetch_some_translations(self, field, languages, *, base_language):
        if not field:
            return {}
        translations = {}
        # If base_language is present in the iterable of languages we want to
        # return a translation for, put it first, so that we can remove
        # translations that don't change anything from the base string.
        languages = [
            base_language,
            *(language for language in languages if language != base_language),
        ]
        for language in languages:
            with override(language):
                value = gettext(field)
                # No point in returning translations that aren't different from
                # the string in the base language.
                if value != translations.get(base_language):
                    translations[language] = value
        return translations

    def fetch_all_translations(self, obj, source, field):
        # TODO: get all locales or KEY_LOCALES_FOR_EDITORIAL_CONTENT at least?
        base_language = to_language(settings.LANGUAGE_CODE)
        current_language = to_language(get_language())
        default_language = getattr(obj, 'default_locale', base_language)

        return self._fetch_some_translations(
            field, {current_language, default_language}, base_language=base_language
        )

    def fetch_single_translation(self, obj, source, field, requested_language):
        base_language = to_language(settings.LANGUAGE_CODE)
        default_language = getattr(obj, 'default_locale', base_language)

        translations = self._fetch_some_translations(
            field,
            {requested_language, default_language},
            base_language=base_language,
        )
        actual_language = (
            requested_language
            if requested_language in translations
            else default_language
            if default_language in translations
            else base_language
        )

        value = translations.get(actual_language)

        return self._format_single_translation_response(
            value,
            actual_language,
            requested_language,
        )

    def to_internal_value(self, data):
        # It wouldn't be impossible to implement this, but we can only write the default
        # locale value, so it'd have to handle that.  Also different l10n data
        # structures for v4 and v5 would be messy. Only used read-only currently.
        raise NotImplementedError


class FieldAlwaysFlatWhenFlatGateActiveMixin:
    """Terribly named mixin to wrap around TranslationSerializerField (and subclasses)
    to always return a single flat string when 'l10n_flat_input_output' is enabled to
    replicate the v4 and earlier behavior in the discovery/hero API."""

    def get_requested_language(self):
        # For l10n_flat_input_output, if the request didn't specify a `lang=xx` then
        # fake it with the current locale so we get a single (flat) result.
        requested = super().get_requested_language()
        if not requested:
            request = self.context.get('request', None)
            if is_gate_active(request, 'l10n_flat_input_output'):
                requested = get_language()
        return requested

    def get_attribute(self, obj):
        # For l10n_flat_input_output, make sure to always return a string as before.
        attribute = super().get_attribute(obj)
        if attribute is None:
            request = self.context.get('request', None)
            if is_gate_active(request, 'l10n_flat_input_output'):
                attribute = ''
        return attribute


class GetTextTranslationSerializerFieldFlat(
    FieldAlwaysFlatWhenFlatGateActiveMixin, GetTextTranslationSerializerField
):
    pass


class TranslationSerializerFieldFlat(
    FieldAlwaysFlatWhenFlatGateActiveMixin, TranslationSerializerField
):
    pass


class FallbackField(fields.Field):
    """
    A wrapper that will return the value from the first field, or the second if the
    first returns a falsey value, (and so on for as many fields passed as args).
    Generally you will need to specify source on at least one of the fields (or they'll
    all be using the same object attribute).
    If used in a write serializer it will be first field that is written.
    Example usage:
    name = FallbackField(
        GetTextTranslationSerializerField(),
        TranslationSerializerField(source='addon.name'),
    )
    """

    label = None

    def __init__(self, *args, **kwargs):
        self.fields = args
        assert len(self.fields) > 0
        kwargs['required'] = self.fields[0].required
        super().__init__(source=self.fields[0].source, **kwargs)

    def bind(self, field_name, parent):
        super().bind(field_name, parent)
        for field in self.fields:
            field.bind(field_name, parent)

    def get_read_only(self):
        return self.fields[0].read_only

    def set_read_only(self, val):
        self.fields[0].read_only = val

    read_only = property(get_read_only, set_read_only)

    def get_value(self, data):
        return self.fields[0].get_value(data)

    def to_internal_value(self, value):
        return self.fields[0].to_internal_value(value)

    def get_attribute(self, obj):
        att = None
        for field in self.fields:
            att = field.get_attribute(obj)
            if att:
                return att
        return att

    def to_representation(self, value):
        rep = None
        for field in self.fields:
            rep = field.to_representation(value)
            if rep:
                return rep
        return rep


class LazyChoiceField(fields.ChoiceField):
    """Like ChoiceField but doesn't end up evaluating `choices` in __init__ so suitable
    for using with queryset."""

    def _get_choices(self):
        return fields.flatten_choices_dict(self.grouped_choices)

    def _set_choices(self, choices):
        self._choices = choices

    @property
    def grouped_choices(self):
        return fields.to_choices_dict(self._choices)

    @property
    def choice_strings_to_values(self):
        # Map the string representation of choices to the underlying value.
        # Allows us to deal with eg. integer choices while supporting either
        # integer or string input, but still get the correct datatype out.
        return {str(key): key for key in self.choices}

    choices = property(_get_choices, _set_choices)
