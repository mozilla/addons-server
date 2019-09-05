from django.db import models
from django_extensions.db.fields.json import JSONField

from olympia.amo.models import ModelBase
from olympia.constants.scanners import SCANNERS
from olympia.files.models import FileUpload


class ScannersResult(ModelBase):
    upload = models.ForeignKey(FileUpload,
                               related_name='scanners_results',
                               on_delete=models.SET_NULL,
                               null=True)
    results = JSONField(default={})
    scanner = models.PositiveSmallIntegerField(choices=SCANNERS)
    version = models.ForeignKey('versions.Version',
                                related_name='scanners_results',
                                on_delete=models.CASCADE,
                                null=True)

    class Meta:
        db_table = 'scanners_results'
        constraints = [
            models.UniqueConstraint(fields=('upload', 'scanner', 'version'),
                                    name='scanners_results_upload_id_scanner_'
                                         'version_id_ad9eb8a6_uniq'),
        ]
