from django.db import models

import caching
from translations.fields import TranslatedFieldMixin, TranslatedField


class ModelBase(caching.CachingMixin, TranslatedFieldMixin, models.Model):
    """
    Base class for AMO models to abstract some common features.

    * Adds automatic created and modified fields to the model.
    * Fetches all translations in one subsequent query during initialization.
    """

    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    objects = caching.CachingManager()

    class Meta:
        abstract = True
        get_latest_by = 'created'


class Application(ModelBase):

    guid = models.CharField(max_length=255, default='')
    name = TranslatedField()
    shortname = TranslatedField()
    supported = models.BooleanField()
    # icondata
    # icontype = models.CharField(max_length=25, default='')

    class Meta:
        db_table = 'applications'

    def __unicode__(self):
        return unicode(self.name)
