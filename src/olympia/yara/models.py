from django.db import models
from django_extensions.db.fields.json import JSONField

from olympia.amo.models import ModelBase
from olympia.files.models import FileUpload


class YaraResult(ModelBase):
    upload = models.OneToOneField(FileUpload,
                                  related_name='yara_results',
                                  on_delete=models.SET_NULL,
                                  null=True)
    matches = JSONField(default=[])
    version = models.OneToOneField('versions.Version',
                                   related_name='yara_results',
                                   on_delete=models.CASCADE,
                                   null=True)

    class Meta:
        db_table = 'yara_results'

    def add_match(self, rule, tags=None, meta=None):
        self.matches.append({
            'rule': rule,
            'tags': tags or [],
            'meta': meta or {},
        })

    @property
    def matched_rules(self):
        return [match['rule'] for match in self.matches]
