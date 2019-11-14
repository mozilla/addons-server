import json

from django.db import models
from django.utils.translation import ugettext_lazy as _
from django_extensions.db.fields.json import JSONField

from olympia.amo.models import ModelBase
from olympia.constants.scanners import (
    ACTIONS,
    CUSTOMS,
    NO_ACTION,
    RESULT_STATES,
    SCANNERS,
    UNKNOWN,
    YARA,
)
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
    matched_rules = models.ManyToManyField(
        'ScannerRule', through='ScannerMatch'
    )
    state = models.PositiveSmallIntegerField(
        choices=RESULT_STATES.items(), null=True, blank=True, default=UNKNOWN
    )

    class Meta:
        db_table = 'scanners_results'
        constraints = [
            models.UniqueConstraint(
                fields=('upload', 'scanner', 'version'),
                name='scanners_results_upload_id_scanner_'
                'version_id_ad9eb8a6_uniq',
            )
        ]
        indexes = [
            models.Index(fields=('has_matches',)),
            models.Index(fields=('state',)),
        ]

    def add_yara_result(self, rule, tags=None, meta=None):
        """This method is used to store a Yara result."""
        self.results.append(
            {'rule': rule, 'tags': tags or [], 'meta': meta or {}}
        )

    def extract_rule_names(self):
        """This method parses the raw results and returns the (matched) rule
        names. Not all scanners have rules that necessarily match."""
        if self.scanner == YARA:
            return sorted({result['rule'] for result in self.results})
        if self.scanner == CUSTOMS and 'matchedRules' in self.results:
            return self.results['matchedRules']
        # We do not have support for the remaining scanners (yet).
        return []

    def save(self, *args, **kwargs):
        matched_rules = ScannerRule.objects.filter(
            scanner=self.scanner, name__in=self.extract_rule_names()
        )
        self.has_matches = bool(matched_rules)
        # Save the instance first...
        super().save(*args, **kwargs)
        # ...then add the associated rules.
        for scanner_rule in matched_rules:
            self.matched_rules.add(scanner_rule)

    def get_scanner_name(self):
        return SCANNERS.get(self.scanner)

    def get_pretty_results(self):
        return json.dumps(self.results, indent=2)


class ScannerRule(ModelBase):
    name = models.CharField(
        max_length=200,
        help_text=_('This is the exact name of the rule used by a scanner.'),
    )
    scanner = models.PositiveSmallIntegerField(choices=SCANNERS.items())
    action = models.PositiveSmallIntegerField(
        choices=ACTIONS.items(), default=NO_ACTION
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'scanners_rules'
        unique_together = ('name', 'scanner')

    def __str__(self):
        return self.name


class ScannerMatch(ModelBase):
    result = models.ForeignKey(ScannerResult, on_delete=models.CASCADE)
    rule = models.ForeignKey(ScannerRule, on_delete=models.CASCADE)
