from django import forms
from django.conf import settings
from django.db import models
from django.db.models.fields import related
from django.utils import translation as translation_utils
from django.utils.translation.trans_real import to_language

from .models import Translation, PurifiedTranslation, LinkifiedTranslation
from .widgets import TranslationWidget


class TranslatedField(models.ForeignKey):
    """
    A foreign key to the translations table.

    If require_locale=False, the fallback join will not use a locale.  Instead,
    we will look for 1) a translation in the current locale and 2) fallback
    with any translation matching the foreign key.
    """
    to = Translation

    def __init__(self, **kwargs):
        # to_field: The field on the related object that the relation is to.
        # Django wants to default to translations.autoid, but we need id.
        options = dict(null=True, to_field='id', unique=True, blank=True)
        kwargs.update(options)
        self.require_locale = kwargs.pop('require_locale', True)
        super(TranslatedField, self).__init__(self.to, **kwargs)

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
        defaults = {'form_class': TranslationFormField}
        defaults.update(kw)
        return super(TranslatedField, self).formfield(**defaults)

    def validate(self, value, model_instance):
        # Skip ForeignKey.validate since that expects only one Translation when
        # doing .get(id=id)
        return models.Field.validate(self, value, model_instance)


class PurifiedField(TranslatedField):
    to = PurifiedTranslation


class LinkifiedField(TranslatedField):
    to = LinkifiedTranslation


def switch(obj, new_model):
    """Switch between Translation and Purified/Linkified Translations."""
    fields = [(f.name, getattr(obj, f.name)) for f in new_model._meta.fields]
    return new_model(**dict(fields))


def save_on_signal(obj, trans):
    """Connect signals so the translation gets saved during obj.save()."""
    signal = models.signals.pre_save
    def cb(sender, instance, **kw):
        if instance is obj:
            trans.save(force_update=True)
            signal.disconnect(cb)
    signal.connect(cb, sender=obj.__class__, weak=False)


class TranslationDescriptor(related.ReverseSingleRelatedObjectDescriptor):
    """
    Descriptor that handles creating and updating Translations given strings.
    """

    def __init__(self, field):
        super(TranslationDescriptor, self).__init__(field)
        self.model = field.rel.to

    def __get__(self, instance, instance_type=None):
        if instance is None:
            return self

        # If Django doesn't find find the value in the cache (which would only
        # happen if the field was set or accessed already), it does a db query
        # to follow the foreign key.  We expect translations to be set by
        # queryset transforms, so doing a query is the wrong thing here.
        try:
            return getattr(instance, self.field.get_cache_name())
        except AttributeError:
            return None

    def __set__(self, instance, value):
        lang = translation_utils.get_language()
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
            if not isinstance(value, self.model):
                value = switch(value, self.model)
            super(TranslationDescriptor, self).__set__(instance, value)

    def translation_from_string(self, instance, lang, string):
        """Create, save, and return a Translation from a string."""
        try:
            trans = getattr(instance, self.field.name)
            trans_id = getattr(instance, self.field.attname)
            if trans is None and trans_id is not None:
                # This locale doesn't have a translation set, but there are
                # translations in another locale, so we have an id already.
                translation = self.model.new(string, lang, id=trans_id)
            elif to_language(trans.locale) == lang.lower():
                # Replace the translation in the current language.
                trans.localized_string = string
                translation = trans
            else:
                # We already have a translation in a different language.
                translation = self.model.new(string, lang, id=trans.id)
        except AttributeError:
            # Create a brand new translation.
            translation = self.model.new(string, lang)
        save_on_signal(instance, translation)
        return translation

    def translation_from_dict(self, instance, lang, dict_):
        """
        Create Translations from a {'locale': 'string'} mapping.

        If one of the locales matches lang, that Translation will be returned.
        """
        rv = None
        for locale, string in dict_.items():
            if locale.lower() not in settings.LANGUAGES:
                continue
            # The Translation is created and saved in here.
            trans = self.translation_from_string(instance, locale, string)

            # Set the Translation on the object because translation_from_string
            # doesn't expect Translations to be created but not attached.
            self.__set__(instance, trans)

            # If we're setting the current locale, set it to the object so
            # callers see the expected effect.
            if to_language(locale) == lang:
                rv = trans
        return rv


class TranslationFormField(forms.Field):
    widget = TranslationWidget

    def __init__(self, *args, **kwargs):
        for k in ('queryset', 'to_field_name'):
            if k in kwargs:
                del kwargs[k]
        super(TranslationFormField, self).__init__(*args, **kwargs)

    def clean(self, value):
        return dict(value)
