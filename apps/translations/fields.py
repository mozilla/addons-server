from django.conf import settings
from django.db import models
from django.db.models.fields import related
from django.utils import translation as translation_utils

from .models import Translation


class TranslatedField(models.ForeignKey):
    """A foreign key to the translations table."""

    def __init__(self):
        # to_field: The field on the related object that the relation is to.
        # Django wants to default to translations.autoid, but we need id.
        options = dict(null=True, to_field='id')
        super(TranslatedField, self).__init__(Translation, **options)

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

        # Set up a unique related name.
        self.rel.related_name = '%s_%s_set' % (cls.__name__, name)

        # Replace the normal descriptor with our custom descriptor.
        setattr(cls, self.name, TranslationDescriptor(self))


class TranslationDescriptor(related.ReverseSingleRelatedObjectDescriptor):
    """
    Descriptor that handles creating and updating Translations given strings.
    """

    def __get__(self, instance, instance_type=None):
        if instance is None:
            return self

        # If Django doesn't find find the value in the cache (which would only
        # happen if the field was set or accessed already), it does a db query
        # to follow the foreign key.  We expect translations to be set by
        # TranslatedFieldMixin, so doing a query is the wrong thing here.
        try:
            return getattr(instance, self.field.get_cache_name())
        except AttributeError:
            return None

    def __set__(self, instance, value):
        if isinstance(value, basestring):
            lang = translation_utils.get_language()
            try:
                trans = getattr(instance, self.field.name)
                trans_id = getattr(instance, self.field.attname)
                if trans is None and trans_id is not None:
                    # This locale doesn't have a translation set, but there are
                    # translations in another locale, so we have an id already.
                    trans = Translation.new(value, lang, id=trans_id)
                elif trans.locale.lower() == lang.lower():
                    # Replace the translation in the current language.
                    trans.localized_string = value
                    trans.save()
                else:
                    # We already have a translation in a different language.
                    trans = Translation.new(value, lang, id=trans.id)
            except AttributeError:
                # Create a brand new translation.
                trans = Translation.new(value, lang)
            value = trans

        # Don't let this be set to None, because Django will then blank out the
        # foreign key for this object.  That's incorrect for translations.
        if value is not None:
            super(TranslationDescriptor, self).__set__(instance, value)


class TranslatedFieldMixin(object):
    """Mixin that fetches all ``TranslatedFields`` after instantiation."""

    def __init__(self, *args, **kw):
        super(TranslatedFieldMixin, self).__init__(*args, **kw)
        self._set_translated_fields()

    def _set_translated_fields(self):
        """Fetch and attach all of this object's translations."""
        if not hasattr(self._meta, 'translated_fields'):
            return

        # Map the attribute name to the object name: 'name_id' => 'name'
        names = dict((f.attname, f.name) for f in self._meta.translated_fields)
        # Map the foreign key to the attribute name: self.name_id => 'name_id'
        ids = dict((getattr(self, name), name) for name in names)

        lang = translation_utils.get_language()
        q = self._fetch_translations(filter(None, ids), lang)

        for translation in q:
            attr = names.pop(ids[translation.id])
            setattr(self, attr, translation)

    def _fetch_translations(self, ids, lang):
        """
        Performs the query for finding Translation objects.

        - ``ids`` is a list of the foreign keys to the object's translations
        - ``lang`` is the language of the current request

        Override this to search for translations in an unusual way.
        """
        fetched = Translation.objects.filter(id__in=ids, locale=lang)

        # Try to find any missing translations in the default locale.
        missing = set(ids).difference(t.id for t in fetched)
        default = settings.LANGUAGE_CODE
        if missing and default != lang:
            fallback = Translation.objects.filter(id__in=missing, locale=default)
            return list(fetched) + list(fallback)
        else:
            return fetched
