from django.core.exceptions import ObjectDoesNotExist, ValidationError
from rest_framework import fields, serializers
from rest_framework.compat import smart_text

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
    A field that accepts a primary key as input but serializes a
    nested representation of the object represented by that key as
    output.
    """
    label = None
    def __init__(self, input, output, **kwargs):
        self.input = input
        self.output = output
        self.source = input.source

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
            raise Exception('Writable related fields must include a `queryset` argument')

        try:
            return self.queryset.get(pk=data)
        except:
            try:
                return self.queryset.get(**{self.slug_field: data})
            except ObjectDoesNotExist:
                msg = self.error_messages['does_not_exist'] % ('pk_or_slug', smart_text(data))
                raise ValidationError(msg)

