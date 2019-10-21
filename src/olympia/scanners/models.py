from django.db import models
from django_extensions.db.fields.json import JSONField

from olympia.amo.models import ModelBase
from olympia.constants.scanners import SCANNERS
from olympia.files.models import FileUpload


class ScannerResult(ModelBase):
    upload = models.ForeignKey(FileUpload,
                               related_name='scanners_results',
                               on_delete=models.SET_NULL,
                               null=True)
    # Store the "raw" results of a scanner (optionally).
    results = JSONField(default=None)
    scanner = models.PositiveSmallIntegerField(choices=SCANNERS.items())
    version = models.ForeignKey('versions.Version',
                                related_name='scanners_results',
                                on_delete=models.CASCADE,
                                null=True)
    matches = JSONField(default=[])
    has_matches = models.NullBooleanField()

    class Meta:
        db_table = 'scanners_results'
        constraints = [
            models.UniqueConstraint(fields=('upload', 'scanner', 'version'),
                                    name='scanners_results_upload_id_scanner_'
                                         'version_id_ad9eb8a6_uniq'),
        ]
        indexes = [
            models.Index(fields=('has_matches',)),
        ]

    def add_match(self, rule, tags=None, meta=None):
        """This method is used to store a matched rule."""
        self.matches.append({
            'rule': rule,
            'tags': tags or [],
            'meta': meta or {},
        })
        self.has_matches = True

    def save(self, *args, **kwargs):
        if self.has_matches is None:
            self.has_matches = bool(self.matches)
        super().save(*args, **kwargs)

    @property
    def matched_rules(self):
        return sorted({match['rule'] for match in self.matches})
