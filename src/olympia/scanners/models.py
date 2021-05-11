import json
import re

from collections import defaultdict
from datetime import datetime

import yara

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from django_jsonfield_backport.models import JSONField

import olympia.core.logger

from olympia.amo.models import ModelBase
from olympia.constants.scanners import (
    ABORTED,
    ABORTING,
    ACTIONS,
    COMPLETED,
    CUSTOMS,
    DELAY_AUTO_APPROVAL,
    DELAY_AUTO_APPROVAL_INDEFINITELY,
    DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT,
    FLAG_FOR_HUMAN_REVIEW,
    QUERY_RULE_STATES,
    MAD,
    NEW,
    NO_ACTION,
    RESULT_STATES,
    RUNNING,
    SCANNERS,
    SCHEDULED,
    UNKNOWN,
    WAT,
    YARA,
)
from olympia.files.models import FileUpload
from olympia.scanners.actions import (
    _delay_auto_approval,
    _delay_auto_approval_indefinitely,
    _delay_auto_approval_indefinitely_and_restrict,
    _flag_for_human_review,
    _flag_for_human_review_by_scanner,
    _no_action,
)


log = olympia.core.logger.getLogger('z.scanners.models')


class AbstractScannerResult(ModelBase):
    # Store the "raw" results of a scanner.
    results = JSONField(default=list)
    scanner = models.PositiveSmallIntegerField(choices=SCANNERS.items())
    has_matches = models.BooleanField(null=True)
    state = models.PositiveSmallIntegerField(
        choices=RESULT_STATES.items(), null=True, blank=True, default=UNKNOWN
    )
    version = models.ForeignKey(
        'versions.Version',
        related_name='%(class)ss',
        on_delete=models.CASCADE,
        null=True,
    )

    class Meta(ModelBase.Meta):
        abstract = True
        indexes = [
            models.Index(fields=('has_matches',)),
            models.Index(fields=('state',)),
        ]

    def add_yara_result(self, rule, tags=None, meta=None):
        """This method is used to store a Yara result."""
        self.results.append({'rule': rule, 'tags': tags or [], 'meta': meta or {}})

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
        rule_model = self._meta.get_field('matched_rules').related_model
        matched_rules = rule_model.objects.filter(
            scanner=self.scanner,
            name__in=self.extract_rule_names(),
            # See: https://github.com/mozilla/addons-server/issues/13143
            is_active=True,
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

    def get_files_by_matched_rules(self):
        res = defaultdict(list)
        if self.scanner is YARA:
            for item in self.results:
                res[item['rule']].append(item['meta'].get('filename', '???'))
        elif self.scanner is CUSTOMS:
            scanMap = self.results.get('scanMap', {})
            for filename, rules in scanMap.items():
                for ruleId, data in rules.items():
                    if data.get('RULE_HAS_MATCHED', False):
                        res[ruleId].append(filename)
        return res

    def can_report_feedback(self):
        return self.state == UNKNOWN and self.scanner not in [WAT, MAD]

    def can_revert_feedback(self):
        return self.state != UNKNOWN and self.scanner not in [WAT, MAD]

    def get_git_repository(self):
        return {
            CUSTOMS: settings.CUSTOMS_GIT_REPOSITORY,
            YARA: settings.YARA_GIT_REPOSITORY,
        }.get(self.scanner)

    @classmethod
    def run_action(cls, version):
        """Try to find and execute an action for a given version, based on the
        scanner results and associated rules.

        If an action is found, it is run synchronously from this method, not in
        a task.
        """
        log.info('Checking rules and actions for version %s.', version.pk)

        try:
            mad_result = cls.objects.filter(version=version, scanner=MAD).get()
            customs = mad_result.results.get('scanners', {}).get('customs', {})
            customs_score = customs.get('score', 0.5)
            customs_models_agree = customs.get('result_details', {}).get(
                'models_agree', True
            )

            if (
                customs_score <= 0.01
                or customs_score >= 0.99
                or not customs_models_agree
            ):
                log.info('Flagging version %s for human review by MAD.', version.pk)
                _flag_for_human_review_by_scanner(version, MAD)
        except cls.DoesNotExist:
            log.info('No MAD scanner result for version %s.', version.pk)
            pass

        rule_model = cls.matched_rules.rel.model
        result_query_name = cls._meta.get_field('matched_rules').related_query_name()

        rule = (
            rule_model.objects.filter(
                **{f'{result_query_name}__version': version, 'is_active': True}
            )
            .order_by(
                # The `-` sign means descending order.
                '-action'
            )
            .first()
        )

        if not rule:
            log.info('No action to execute for version %s.', version.pk)
            return

        action_id = rule.action
        action_name = ACTIONS.get(action_id, None)

        if not action_name:
            raise Exception('invalid action %s' % action_id)

        ACTION_FUNCTIONS = {
            NO_ACTION: _no_action,
            FLAG_FOR_HUMAN_REVIEW: _flag_for_human_review,
            DELAY_AUTO_APPROVAL: _delay_auto_approval,
            DELAY_AUTO_APPROVAL_INDEFINITELY: _delay_auto_approval_indefinitely,
            DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT: (
                _delay_auto_approval_indefinitely_and_restrict
            ),
        }

        action_function = ACTION_FUNCTIONS.get(action_id, None)

        if not action_function:
            raise Exception('no implementation for action %s' % action_id)

        # We have a valid action to execute, so let's do it!
        log.info('Starting action "%s" for version %s.', action_name, version.pk)
        action_function(version)
        log.info('Ending action "%s" for version %s.', action_name, version.pk)


class AbstractScannerRule(ModelBase):
    name = models.CharField(
        max_length=200,
        help_text=_('This is the exact name of the rule used by a scanner.'),
    )
    scanner = models.PositiveSmallIntegerField(choices=SCANNERS.items())
    action = models.PositiveSmallIntegerField(
        choices=ACTIONS.items(), default=NO_ACTION
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_(
            'When unchecked, the scanner results will not be bound to this '
            'rule and the action will not be executed.'
        ),
    )
    definition = models.TextField(null=True, blank=True)

    class Meta(ModelBase.Meta):
        abstract = True
        unique_together = ('name', 'scanner')

    @classmethod
    def get_yara_externals(cls):
        """
        Return a dict with the various external variables we inject in every
        yara rule automatically and their default values.
        """
        return {
            'is_json_file': False,
            'is_manifest_file': False,
            'is_locale_file': False,
        }

    def __str__(self):
        return self.name

    def clean(self):
        if self.scanner == YARA:
            self.clean_yara()

    def clean_yara(self):
        if not self.definition:
            raise ValidationError(
                {'definition': _('Yara rules should have a definition')}
            )

        if 'rule {}'.format(self.name) not in self.definition:
            raise ValidationError(
                {
                    'definition': _(
                        'The name of the rule in the definition should match '
                        'the name of the scanner rule'
                    )
                }
            )

        if len(re.findall(r'rule\s+.+?\s+{', self.definition)) > 1:
            raise ValidationError(
                {'definition': _('Only one Yara rule is allowed in the definition')}
            )

        try:
            yara.compile(source=self.definition, externals=self.get_yara_externals())
        except yara.SyntaxError as syntaxError:
            raise ValidationError(
                {
                    'definition': _('The definition is not valid: %(error)s')
                    % {'error': syntaxError}
                }
            )
        except Exception:
            raise ValidationError(
                {'definition': _('An error occurred when compiling the definition')}
            )


class ScannerRule(AbstractScannerRule):
    class Meta(AbstractScannerRule.Meta):
        db_table = 'scanners_rules'


class ScannerResult(AbstractScannerResult):
    upload = models.ForeignKey(
        FileUpload,
        related_name='%(class)ss',  # scannerresults
        on_delete=models.SET_NULL,
        null=True,
    )
    matched_rules = models.ManyToManyField(
        'ScannerRule', through='ScannerMatch', related_name='results'
    )
    # The value is a decimal between 0 and 1. `-1` is a special value to
    # indicate an error or no score available.
    score = models.DecimalField(
        null=True, blank=True, max_digits=6, decimal_places=5, default=-1
    )
    model_version = models.CharField(max_length=30, null=True)

    class Meta(AbstractScannerResult.Meta):
        db_table = 'scanners_results'
        constraints = [
            models.UniqueConstraint(
                fields=('upload', 'scanner', 'version'),
                name='scanners_results_upload_id_scanner_version_id_ad9eb8a6_uniq',
            )
        ]


class ScannerMatch(ModelBase):
    result = models.ForeignKey(ScannerResult, on_delete=models.CASCADE)
    rule = models.ForeignKey(ScannerRule, on_delete=models.CASCADE)


class ImproperScannerQueryRuleStateError(ValueError):
    pass


class ScannerQueryRule(AbstractScannerRule):
    scanner = models.PositiveSmallIntegerField(
        choices=((YARA, 'yara'),),  # For now code search only allows yara.
        default=YARA,
    )
    state = models.PositiveSmallIntegerField(
        choices=QUERY_RULE_STATES.items(), default=NEW
    )
    run_on_disabled_addons = models.BooleanField(
        default=False,
        help_text=_('Run this rule on add-ons that have been force-disabled as well.'),
    )
    celery_group_result_id = models.UUIDField(default=None, null=True)
    task_count = models.PositiveIntegerField(default=0)
    completed = models.DateTimeField(default=None, null=True, blank=True)

    class Meta(AbstractScannerRule.Meta):
        db_table = 'scanners_query_rules'

    def change_state_to(self, target):
        """Immediately change state of the rule in database or raise
        ImproperScannerQueryRuleStateError."""
        prereqs = {
            # New is the default state.
            NEW: (),
            # Scheduled should only happen through the admin. It's the
            # prerequisite to running the task.
            SCHEDULED: (NEW,),
            # Running should only happen through the task, after we went
            # through the admin to schedule the query.
            RUNNING: (SCHEDULED,),
            # Aborting can happen from various states.
            ABORTING: (NEW, SCHEDULED, RUNNING),
            # Aborted should only happen after aborting.
            ABORTED: (ABORTING,),
            # Completed should only happen through the task
            COMPLETED: (RUNNING,),
        }
        if self.state in prereqs[target]:
            props = {
                'state': target,
            }
            if target == COMPLETED:
                props['completed'] = datetime.now()
            self.update(**props)
        else:
            raise ImproperScannerQueryRuleStateError()

    def _get_completed_tasks_count(self):
        if self.celery_group_result_id is not None:
            from olympia.amo.celery import app as celery_app

            result = celery_app.GroupResult.restore(str(self.celery_group_result_id))
            if result:
                return result.completed_count()
        return None

    def completion_rate(self):
        if self.state == RUNNING:
            completed_tasks_count = self._get_completed_tasks_count()
            if completed_tasks_count is not None and self.task_count:
                rate = (completed_tasks_count / self.task_count) * 100
                return '{:.2f}%'.format(rate)
        return None


class ScannerQueryResult(AbstractScannerResult):
    # Has to be overridden, because the parent refers to ScannerMatch.
    matched_rules = models.ManyToManyField(
        'ScannerQueryRule', through='ScannerQueryMatch', related_name='results'
    )
    was_blocked = models.BooleanField(null=True, default=None)

    class Meta(AbstractScannerResult.Meta):
        db_table = 'scanners_query_results'
        # FIXME indexes, unique constraints ?


class ScannerQueryMatch(ModelBase):
    result = models.ForeignKey(ScannerQueryResult, on_delete=models.CASCADE)
    rule = models.ForeignKey(ScannerQueryRule, on_delete=models.CASCADE)
