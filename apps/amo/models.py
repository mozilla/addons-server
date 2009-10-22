from django.db import models


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
        q = Translation.objects.filter(id=value, locale=locale)
        v = q.values_list('localized_string', flat=True)
        return v[0] if v else value


# Putting Translation in here since TranslatedField depends on it.
class Translation(LegacyModel):

    autoid = models.AutoField(primary_key=True)
    id = models.IntegerField()
    locale = models.CharField(max_length=10)
    localized_string = models.TextField()

    class Meta:
        db_table = 'translations'
