from django.db import models
from django_extensions.db.fields.json import JSONField

from olympia.amo.models import ModelBase
from olympia.files.models import FileUpload


class YaraResult(ModelBase):
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

    def add_match(self, rule, tags=[], meta={}):
        self.matches.append({
            'rule': rule,
            'tags': tags,
            'meta': meta,
        })
