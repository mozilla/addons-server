from collections import namedtuple

from django import forms
from django.conf import settings
from django.db import models
from django.db.models.fields import related
from django.utils import translation as translation_utils
from django.utils.translation.trans_real import to_language

from .hold import add_translation, make_key, save_translations
from .widgets import TransInput, TransTextarea


LocaleErrorMessage = namedtuple('LocaleErrorMessage', 'message locale')


class TranslatedField(models.ForeignKey):
    """
    A foreign key to the translations table.

    If require_locale=False, the fallback join will not use a locale.  Instead,
    we will look for 1) a translation in the current locale and 2) fallback
    with any translation matching the foreign key.
    """
    to = 'translations.Translation'
    requires_unique_target = False

    def __init__(self, **kwargs):
        # to_field: The field on the related object that the relation is to.
        # Django wants to default to translations.autoid, but we need id.
        kwargs.update({
            'null': True,
            'to_field': 'id',
            'unique': True,
            'blank': True,
            'on_delete': models.SET_NULL
        })

        self.short = kwargs.pop('short', True)
        self.require_locale = kwargs.pop('require_locale', True)

        # "to" is passed here from the migration framework; we ignore it
        # since it's the same for every instance.
        kwargs.pop('to', None)
        super(TranslatedField, self).__init__(self.to, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super(TranslatedField, self).deconstruct()
        kwargs['to'] = self.to
        kwargs['short'] = self.short
        kwargs['require_locale'] = self.require_locale
        return (name, path, args, kwargs)

    @property
    def db_column(self):
        # Django wants to call the db_column ('%s_id' % self.name), but our
        # translations foreign keys aren't set up that way.
        return self._db_column if hasattr(self, '_db_column') else self.name

    @db_column.setter
    def db_column(self, value):
        # Django sets db_column=None to initialize it.  I don't think anyone
        # would set the db_column otherwise.
        if value is not None:
            self._db_column = value

    def contribute_to_class(self, cls, name):
        """Add this Translation to ``cls._meta.translated_fields``."""
        super(TranslatedField, self).contribute_to_class(cls, name)

        # Add self to the list of translated fields.
        if hasattr(cls._meta, 'translated_fields'):
            cls._meta.translated_fields.append(self)
        else:
            cls._meta.translated_fields = [self]

        # Set up a unique related name.  The + means it's hidden.
        self.rel.related_name = '%s_%s_set+' % (cls.__name__, name)

        # Replace the normal descriptor with our custom descriptor.
        setattr(cls, self.name, TranslationDescriptor(self))

    def formfield(self, **kw):
        widget = TransInput if self.short else TransTextarea
        defaults = {'form_class': TransField, 'widget': widget}
        defaults.update(kw)
        return super(TranslatedField, self).formfield(**defaults)

    def validate(self, value, model_instance):
        # Skip ForeignKey.validate since that expects only one Translation when
        # doing .get(id=id)
        return models.Field.validate(self, value, model_instance)


class PurifiedField(TranslatedField):
    to = 'translations.PurifiedTranslation'


class LinkifiedField(TranslatedField):
    to = 'translations.LinkifiedTranslation'


class NoLinksField(TranslatedField):
    to = 'translations.NoLinksTranslation'


class NoLinksNoMarkupField(TranslatedField):
    to = 'translations.NoLinksNoMarkupTranslation'


def switch(obj, new_model):
    """Switch between Translation and Purified/Linkified Translations."""
    fields = [
        (f.name, getattr(obj, f.name, None))
        for f in new_model._meta.fields]
    return new_model(**dict(fields))


def save_on_signal(obj, trans):
    """Connect signals so the translation gets saved during obj.save()."""
    signal = models.signals.pre_save

    def cb(sender, instance, **kw):
        if instance is obj:
            is_new = trans.autoid is None
            trans.save(force_insert=is_new, force_update=not is_new)
            signal.disconnect(cb)
    signal.connect(cb, sender=obj.__class__, weak=False)


class TranslationDescriptor(related.ForwardManyToOneDescriptor):
    """
    Descriptor that handles creating and updating Translations given strings.
    """
    def __get__(self, instance, cls=None):
        if instance is None:
            return self

        # If Django doesn't find find the value in the cache (which would only
        # happen if the field was set or accessed already), it does a db query
        # to follow the foreign key. We expect translations to be set by
        # queryset transforms, so doing a query is the wrong thing here.
        try:
            return getattr(instance, self.cache_name)
        except AttributeError:
            return None

    def __set__(self, instance, value):
        lang = translation_utils.get_language()
        #print('__set__', instance, instance.pk, value, lang)
        if isinstance(value, basestring):
            value = self.translation_from_string(instance, lang, value)
        elif hasattr(value, 'items'):
            value = self.translation_from_dict(instance, lang, value)

        # Don't let this be set to None, because Django will then blank out the
        # foreign key for this object.  That's incorrect for translations.
        if value is not None:
            # We always get these back from the database as Translations, but
            # we may want them to be a more specific Purified/Linkified child
            # class.
            if not isinstance(value, self.field.related_model):
                value = switch(value, self.field.related_model)
            super(TranslationDescriptor, self).__set__(instance, value)
        elif getattr(instance, self.field.column, None) is None:
            super(TranslationDescriptor, self).__set__(instance, None)

        # print(
        #     'after __set__',
        #     getattr(instance, self.cache_name), instance, instance.pk, value,
        #     lang)
        # print()

    def translation_from_string(self, instance, lang, string):
        """Create, save, and return a Translation from a string."""
        trans_id = instance.__dict__.get(self.field.attname)
        if trans_id is None:
            # We don't have a translation for this field in any language,
            # create a brand new one.
            translation = self.field.related_model.new(string, lang)
        else:
            try:
                trans = getattr(instance, self.field.name)
            except AttributeError, instance.DoesNotExist:
                trans = None
            if trans is not None and to_language(trans.locale) == lang.lower():
                # Replace the translation in the current language.
                trans.localized_string = string
                translation = trans
            else:
                # We either could not find a translation (but know that one
                # already exist, because trans_id is set) or are looking to
                # create one in a different language anyway.
                translation = self.field.related_model.new(
                    string, lang, id=trans_id)

        # A new translation has been created and it might need to be saved.
        # This adds the translation to the queue of translation that need
        # to be saved for this instance.
        add_translation(make_key(instance), translation)
        return translation

    def translation_from_dict(self, instance, lang, dict_):
        """
        Create Translations from a {'locale': 'string'} mapping.

        If one of the locales matches lang, that Translation will be returned.
        """
        from olympia.amo.utils import to_language as amo_to_language

        rv = None
        for locale, string in dict_.items():
            loc = amo_to_language(locale)
            if loc not in settings.AMO_LANGUAGES:
                continue

            # The Translation is created and saved in here.
            trans = self.translation_from_string(instance, locale, string)

            # Set the Translation on the object because translation_from_string
            # doesn't expect Translations to be created but not attached.
            print('set trans on instance', instance, trans)
            self.__set__(instance, trans)

            # If we're setting the current locale, set it to the object so
            # callers see the expected effect.
            if to_language(locale) == lang:
                rv = trans

        self.__set__(instance, rv)
        return rv


class _TransField(object):

    def __init__(self, *args, **kwargs):
        self.default_locale = settings.LANGUAGE_CODE
        for k in ('queryset', 'to_field_name', 'limit_choices_to'):
            if k in kwargs:
                del kwargs[k]
        self.widget = kwargs.pop('widget', TransInput)

        # XXX: Figure out why this is being forwarded here (cgrebs)
        # It's empty and not supported by CharField (-> TransField)
        kwargs.pop('limit_choices_to', None)
        super(_TransField, self).__init__(*args, **kwargs)

    def set_default_values(self, field_name, parent_form, default_locale):
        self.parent_form = parent_form
        self.default_locale = default_locale
        self.widget.default_locale = default_locale
        self._field_name = field_name

    def clean(self, value):
        value = dict((k, v.strip() if v else v) for (k, v) in value.items())

        # Raise an exception if the default locale is required and not present
        if self.default_locale.lower() not in value:
            value[self.default_locale.lower()] = None

        # Now, loop through them and validate them separately.
        for locale, val in value.items():
            try:
                # Only the default locale can be required; all non-default
                # fields are automatically optional.
                if self.default_locale.lower() == locale:
                    super(_TransField, self).validate(val)
                super(_TransField, self).run_validators(val)
            except forms.ValidationError, e:
                for message in e.messages:
                    self.parent_form.add_error(
                        self._field_name,
                        LocaleErrorMessage(message=message, locale=locale))
        return value

    def has_changed(self, initial, data):
        # This used to be called on the field's widget and always returned
        # False!
        return False


class TransField(_TransField, forms.CharField):
    """
    A CharField subclass that can deal with multiple locales.

    Most validators are run over the data for each locale.  The required
    validator is only run on the default_locale, which is hooked up to the
    instance with TranslationFormMixin.
    """

    @staticmethod
    def adapt(cls, opts=None):
        """Get a new TransField that subclasses cls instead of CharField."""
        if opts is None:
            opts = {}
        return type('Trans%s' % cls.__name__, (_TransField, cls), opts)


def save_signal(sender, instance, **kw):
    """
    Use this signal on a model to iterate through all the translations added
    to the hold queue and save them all. Hook this up to the pre_save signal
    on the model.
    """
    if not kw.get('raw'):
        save_translations(make_key(instance))
