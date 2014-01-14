from django.core import validators
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models.fields import BLANK_CHOICE_DASH
from django.utils.translation import ugettext_lazy as _

from rest_framework import fields, serializers
from rest_framework.compat import smart_text

from amo.utils import to_language


class MultiSlugChoiceField(fields.WritableField):
    """
    Like SlugChoiceField but accepts a list of values rather a single one.
    """
    type_name = 'MultiSlugChoiceField'
    type_label = 'multiple choice'
    default_error_messages = {
        'invalid_choice': _('Select a valid choice. %(value)s is not one of '
                            'the available choices.'),
    }

    def __init__(self, choices_dict=None, *args, **kwargs):
        super(MultiSlugChoiceField, self).__init__(*args, **kwargs)
        # Create a choice dynamically to allow None, slugs and ids. Also store
        # choices_dict and ids_choices_dict to re-use them later in to_native()
        # and from_native().
        self.choices_dict = choices_dict
        slugs_choices = self.choices_dict.items()
        ids_choices = [(v.id, v) for v in self.choices_dict.values()]
        self.ids_choices_dict = dict(ids_choices)
        self.choices = slugs_choices + ids_choices
        if not self.required:
            self.choices = BLANK_CHOICE_DASH + self.choices

    def validate(self, value):
        """
        Validates that the input is in self.choices.
        """
        super(MultiSlugChoiceField, self).validate(value)
        for v in value:
            if not self.valid_value(v):
                raise ValidationError(self.error_messages['invalid_choice'] % {
                    'value': v})

    def valid_value(self, value):
        """
        Check to see if the provided value is a valid choice.
        """
        for k, v in self.choices:
            if isinstance(v, (list, tuple)):
                # This is an optgroup, so look inside the group for options
                for k2, v2 in v:
                    if value == smart_text(k2):
                        return True
            else:
                if value == smart_text(k) or value == k:
                    return True
        return False

    def from_native(self, value):
        if value in validators.EMPTY_VALUES:
            return None
        return super(MultiSlugChoiceField, self).from_native(value)


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
        source = self.source or field_name
        value = obj
        for component in source.split('.'):
            value = fields.get_component(value, component)
            if value is None:
                break

        field = value
        if field is None:
            return None
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


class SplitField(fields.Field):
    """
    A field composed of two separate fields: one used for input, and another
    used for output. Most commonly used to accept a primary key for input and
    use a full serializer for output.

    Example usage:
    app = SplitField(PrimaryKeyRelatedField(), AppSerializer())
    """
    label = None

    def __init__(self, input, output, **kwargs):
        self.input = input
        self.output = output
        self.source = input.source
        self._read_only = False

    def initialize(self, parent, field_name):
        """
        Update the context of the input and output fields to match the context
        of this field.
        """
        super(SplitField, self).initialize(parent, field_name)
        for field in [self.input, self.output]:
            if hasattr(field, 'context'):
                field.context.update(self.context)

    def get_read_only(self):
        return self._read_only

    def set_read_only(self, val):
        self._read_only = val
        self.input.read_only = val
        self.output.read_only = val

    read_only = property(get_read_only, set_read_only)

    def field_from_native(self, data, files, field_name, into):
        self.input.initialize(parent=self.parent, field_name=field_name)
        self.input.field_from_native(data, files, field_name, into)

    def field_to_native(self, obj, field_name):
        self.output.initialize(parent=self.parent, field_name=field_name)
        return self.output.field_to_native(obj, field_name)


class SlugOrPrimaryKeyRelatedField(serializers.RelatedField):
    """
    Combines SlugRelatedField and PrimaryKeyRelatedField. Takes a
    `render_as` argument (either "pk" or "slug") to indicate how to
    serialize.
    """
    default_error_messages = serializers.SlugRelatedField.default_error_messages
    read_only = False

    def __init__(self, *args, **kwargs):
        self.render_as = kwargs.pop('render_as', 'pk')
        if self.render_as not in ['pk', 'slug']:
            raise ValueError("'render_as' must be one of 'pk' or 'slug', "
                             "not %r" % (self.render_as,))
        self.slug_field = kwargs.pop('slug_field', 'slug')
        super(SlugOrPrimaryKeyRelatedField, self).__init__(
            *args, **kwargs)

    def to_native(self, obj):
        if self.render_as == 'slug':
            return getattr(obj, self.slug_field)
        else:
            return obj.pk

    def from_native(self, data):
        if self.queryset is None:
            raise Exception('Writable related fields must include a `queryset` '
                            'argument')

        try:
            return self.queryset.get(pk=data)
        except:
            try:
                return self.queryset.get(**{self.slug_field: data})
            except ObjectDoesNotExist:
                msg = self.error_messages['does_not_exist'] % (
                    'pk_or_slug', smart_text(data))
                raise ValidationError(msg)


class ReverseChoiceField(serializers.ChoiceField):
    """
    A ChoiceField that serializes and de-serializes using the human-readable
    version of the `choices_dict` that is passed.

    The values in the choices_dict passed must be unique.
    """
    def __init__(self, *args, **kwargs):
        self.choices_dict = kwargs.pop('choices_dict')
        kwargs['choices'] = self.choices_dict.items()
        self.reversed_choices_dict = dict((v, k) for k, v
                                          in self.choices_dict.items())
        return super(ReverseChoiceField, self).__init__(*args, **kwargs)

    def to_native(self, value):
        """
        Convert "actual" value to "human-readable" when serializing.
        """
        value = self.choices_dict.get(value, None)
        return super(ReverseChoiceField, self).to_native(value)

    def from_native(self, value):
        """
        Convert "human-readable" value to "actual" when de-serializing.
        """
        value = self.reversed_choices_dict.get(value, None)
        return super(ReverseChoiceField, self).from_native(value)


class SlugChoiceField(serializers.ChoiceField):
    """
    Companion to SlugChoiceFilter, this field accepts an id or a slug when
    de-serializing, but always return a slug for serializing.

    Like SlugChoiceFilter, it needs to be initialized with a `choices_dict`
    mapping the slugs to objects with id and slug properties. This will be used
    to overwrite the choices in the underlying code.

    The values in the choices_dict passed must be unique.
    """
    def __init__(self, *args, **kwargs):
        # Create a choice dynamically to allow None, slugs and ids. Also store
        # choices_dict and ids_choices_dict to re-use them later in to_native()
        # and from_native().
        self.choices_dict = kwargs.pop('choices_dict')
        slugs_choices = self.choices_dict.items()
        ids_choices = [(v.id, v) for v in self.choices_dict.values()]
        self.ids_choices_dict = dict(ids_choices)
        kwargs['choices'] = slugs_choices + ids_choices
        return super(SlugChoiceField, self).__init__(*args, **kwargs)

    def to_native(self, value):
        if value:
            choice = self.ids_choices_dict.get(value, None)
            if choice is not None:
                value = choice.slug
        return super(SlugChoiceField, self).to_native(value)

    def from_native(self, value):
        if isinstance(value, basestring):
            choice = self.choices_dict.get(value, None)
            if choice is not None:
                value = choice.id
        return super(SlugChoiceField, self).from_native(value)


class SlugModelChoiceField(serializers.PrimaryKeyRelatedField):
    def field_to_native(self, obj, field_name):
        attr = self.source or field_name
        value = getattr(obj, attr)
        return getattr(value, 'slug', None)

    def from_native(self, data):
        if isinstance(data, basestring):
            try:
                data = self.queryset.only('pk').get(slug=data).pk
            except ObjectDoesNotExist:
                msg = self.error_messages['does_not_exist'] % smart_text(data)
                raise serializers.ValidationError(msg)
        return super(SlugModelChoiceField, self).from_native(data)


class LargeTextField(serializers.HyperlinkedRelatedField):
    """
    Accepts a value for a field when unserializing, but serializes as
    a link to a separate resource. Used for text too long for common
    inclusion in a resource.
    """
    def field_to_native(self, obj, field_name):
        return self.to_native(obj)

    def from_native(self, value):
        return value
