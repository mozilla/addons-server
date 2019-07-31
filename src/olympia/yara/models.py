from django.db import models
from django_extensions.db.fields.json import JSONField

from olympia.amo.models import ModelBase
from olympia.files.models import FileUpload


class YaraResults(ModelBase):
    upload = models.OneToOneField(FileUpload,
                                  related_name='yara_results',
                                  on_delete=models.CASCADE)
    matches = JSONField(default=[])
    version = models.OneToOneField('versions.Version',
                                   related_name='yara_results',
                                   on_delete=models.CASCADE,
                                   null=True)

    class Meta:
        db_table = 'yara_results'
        verbose_name_plural = 'yara results'
