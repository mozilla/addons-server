from django.db import models
from django.utils import translation as translation_utils


class ModelBase(models.Model):
    """
    Base class for AMO models to abstract some common features.

    * Adds automatic created and modified fields to the model.
    * Fetches all translations in one subsequent query during initialization
    """

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __init__(self, *args, **kw):
        super(ModelBase, self).__init__(*args, **kw)
        self.set_tranlated_fields()

    def set_tranlated_fields(self):
        """Fetch and attach all of this object's translations."""
        if not hasattr(self._meta, 'translated_fields'):
            return

        # Map the attribute name to the object name: 'name_id' => 'name'
        names = dict((f.attname, f.name) for f in self._meta.translated_fields)
        # Map the foreign key to the attribute name: self.name_id => 'name_id'
        ids = dict((getattr(self, name), name) for name in names)

        Translation = self._meta.translated_fields[0].rel.to
        lang = translation_utils.get_language()
        q = self._fetch_translations(Translation, ids, lang)

        for translation in q:
            attr = names[ids[translation.id]]
            setattr(self, attr, translation)

    def _fetch_translations(self, Translation, ids, lang):
        """
        Performs the query for finding Translation objects.

        ``Translation`` is the :class:`translations.Translation` class
        ``ids`` is a list of the foreign keys to the object's translations
        ``lang`` is the language of the current request

        Override this to search for translations in an unusual way.
        """
        return Translation.objects.filter(id__in=ids, locale=lang)
