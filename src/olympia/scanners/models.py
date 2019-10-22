from django.db import models
from django.utils.translation import ugettext_lazy as _
from django_extensions.db.fields.json import JSONField

from olympia.amo.models import ModelBase
from olympia.constants.scanners import SCANNERS, ACTIONS, NO_ACTION, YARA
from olympia.files.models import FileUpload


class ScannerResult(ModelBase):
    upload = models.ForeignKey(
        FileUpload,
        related_name='scanners_results',
        on_delete=models.SET_NULL,
        null=True,
    )
    # Store the "raw" results of a scanner.
    results = JSONField(default=[])
    scanner = models.PositiveSmallIntegerField(choices=SCANNERS.items())
    version = models.ForeignKey(
        'versions.Version',
        related_name='scanners_results',
        on_delete=models.CASCADE,
        null=True,
    )
    has_matches = models.NullBooleanField()

    class Meta:
        db_table = 'scanners_results'
        constraints = [
            models.UniqueConstraint(
                fields=('upload', 'scanner', 'version'),
                name='scanners_results_upload_id_scanner_'
                'version_id_ad9eb8a6_uniq',
            )
        ]
        indexes = [models.Index(fields=('has_matches',))]

    def add_yara_result(self, rule, tags=None, meta=None):
        """This method is used to store a Yara result."""
        self.results.append(
            {'rule': rule, 'tags': tags or [], 'meta': meta or {}}
        )
        self.has_matches = True

    def save(self, *args, **kwargs):
        if self.has_matches is None:
            self.has_matches = bool(self.results)
        super().save(*args, **kwargs)

    @property
    def matched_rules(self):
        if self.scanner is not YARA:
            # We do not have support for other scanners yet.
            return []
        """This method returns a sorted list of matched rule names."""
        return sorted({match['rule'] for match in self.results})


class ScannerRule(ModelBase):
    name = models.CharField(
        max_length=200,
        unique=True,
        help_text=_('This is the exact name of the rule used by a scanner.'),
    )
    scanner = models.PositiveSmallIntegerField(choices=SCANNERS.items())
    action = models.PositiveSmallIntegerField(
        choices=ACTIONS.items(), default=NO_ACTION
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'scanners_rules'

    def __str__(self):
        return self.name
