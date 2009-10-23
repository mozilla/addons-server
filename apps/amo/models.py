from django.db import models

from . import managers


class LegacyModel(models.Model):
    """Adds automatic created and modified fields to the model."""
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TranslatedField(models.IntegerField):
    __metaclass__ = models.SubfieldBase

    def to_python(self, value):
        locale = 'en-US'
        try:
            o = Translation.objects.get(id=value, locale=locale)
            return o.localized_string
        except Translation.DoesNotExist:
            return value


# Putting Translation in here since TranslatedField depends on it.
class Translation(LegacyModel):

    autoid = models.AutoField(primary_key=True)
    id = models.IntegerField()
    locale = models.CharField(max_length=10)
    localized_string = models.TextField()

    objects = managers.CachingManager()

    class Meta:
        db_table = 'translations'

    @property
    def cache_key(self):
        return self._cache_key(id=self.id, locale=self.locale)
