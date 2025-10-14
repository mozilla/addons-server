import json
import re
from collections import defaultdict
from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.functional import classproperty

import yara

import olympia.core.logger
from olympia import amo
from olympia.amo.models import ModelBase
from olympia.constants.base import ADDON_EXTENSION
from olympia.constants.scanners import (
    ABORTED,
    ABORTING,
    ACTIONS,
    COMPLETED,
    CUSTOMS,
    DELAY_AUTO_APPROVAL,
    DELAY_AUTO_APPROVAL_INDEFINITELY,
    DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT,
    DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT_FUTURE_APPROVALS,
    DISABLE_AND_BLOCK,
    FLAG_FOR_HUMAN_REVIEW,
    NARC,
    NEW,
    NO_ACTION,
    QUERY_RULE_STATES,
    RESULT_STATES,
    RUNNING,
    SCANNERS,
    SCHEDULED,
    UNKNOWN,
    YARA,
)
from olympia.files.models import FileUpload
from olympia.scanners.actions import (
    _delay_auto_approval,
    _delay_auto_approval_indefinitely,
    _delay_auto_approval_indefinitely_and_restrict,
    _delay_auto_approval_indefinitely_and_restrict_future_approvals,
    _disable_and_block,
    _flag_for_human_review,
    _no_action,
)


log = olympia.core.logger.getLogger('z.scanners.models')


class AbstractScannerResult(ModelBase):
    # Store the "raw" results of a scanner.
    results = models.JSONField(default=list)
    scanner = models.PositiveSmallIntegerField(choices=SCANNERS.items())
    version = models.ForeignKey(
        'versions.Version',
        related_name='%(class)ss',
        on_delete=models.CASCADE,
        null=True,
    )

    class Meta(ModelBase.Meta):
        abstract = True

    def add_yara_result(self, rule, tags=None, meta=None):
        """This method is used to store a Yara result."""
        self.results.append({'rule': rule, 'tags': tags or [], 'meta': meta or {}})

    def extract_rule_names(self):
        """This method parses the raw results and returns the (matched) rule
        names. Not all scanners have rules that necessarily match."""
        if self.scanner in (NARC, YARA):
            return sorted({result['rule'] for result in self.results})
        if self.scanner == CUSTOMS and 'matchedRules' in self.results:
            return self.results['matchedRules']
        # We do not have support for the remaining scanners (yet).
        return []

    def get_rules_queryset(self):
        """Helper to return the rule(s) queryset matching the rule name and
        scanner for this result."""
        return self.rule_model.objects.filter(
            scanner=self.scanner,
            name__in=self.extract_rule_names(),
        )

    @classproperty
    def rule_model(self):
        # Implement in concrete models.
        raise NotImplementedError

    def get_scanner_name(self):
        return SCANNERS.get(self.scanner)

    def get_pretty_results(self):
        return json.dumps(self.results, indent=2)

    def get_files_and_data_by_matched_rules(self):
        """
        Return results metadata from matched rules

        This includes the filename that matched if applicable and the name of
        the rule, but excluding info that would reveal the definition of the
        rule itself, such as the pattern for NARC).
        """
        res = defaultdict(list)
        if self.scanner == YARA:
            for item in self.results:
                res[item['rule']].append(
                    {'filename': item.get('meta', {}).get('filename', '???')}
                )
        elif self.scanner == NARC:
            for item in self.results:
                meta = item.get('meta', {}).copy()
                for field in ('pattern', 'span'):
                    meta.pop(field, None)
                res[item['rule']].append(meta)
        elif self.scanner == CUSTOMS:
            scanMap = self.results.get('scanMap', {}).copy()
            for filename, rules in scanMap.items():
                for ruleId, data in rules.items():
                    data = data.copy()
                    if data.pop('RULE_HAS_MATCHED', False):
                        if filename == '__GLOBAL__':
                            filename = ''
                        res[ruleId].append({'filename': filename, 'data': data})
        return res

    def get_git_repository(self):
        return {
            CUSTOMS: settings.CUSTOMS_GIT_REPOSITORY,
        }.get(self.scanner)


class AbstractScannerRule(ModelBase):
    name = models.CharField(
        max_length=200,
        help_text='This is the exact name of the rule used by a scanner.',
    )
    pretty_name = models.CharField(
        default='',
        help_text='Human-readable name for the scanner rule',
        max_length=255,
        blank=True,
        verbose_name='Human-readable name',
    )
    description = models.CharField(
        default='',
        help_text='Human readable description for the scanner rule',
        max_length=255,
        blank=True,
    )
    scanner = models.PositiveSmallIntegerField(choices=SCANNERS.items())
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
        return self.pretty_name or self.name

    def clean(self):
        if self.scanner == YARA:
            self.clean_yara()
        elif self.scanner == NARC:
            self.clean_narc()

    def clean_narc(self):
        if not self.definition:
            raise ValidationError({'definition': 'Narc rules should have a definition'})
        try:
            re.compile(self.definition)
        except Exception as exc:
            raise ValidationError(
                {'definition': 'An error occurred when compiling regular expression'}
            ) from exc

    def clean_yara(self):
        if not self.definition:
            raise ValidationError({'definition': 'Yara rules should have a definition'})

        if f'rule {self.name}' not in self.definition:
            raise ValidationError(
                {
                    'definition': (
                        'The name of the rule in the definition should match '
                        'the name of the scanner rule'
                    )
                }
            )

        if len(re.findall(r'rule\s+.+?\s+{', self.definition)) > 1:
            raise ValidationError(
                {'definition': 'Only one Yara rule is allowed in the definition'}
            )

        try:
            yara.compile(source=self.definition, externals=self.get_yara_externals())
        except yara.SyntaxError as syntaxError:
            raise ValidationError(
                {
                    'definition': 'The definition is not valid: %(error)s'
                    % {'error': syntaxError}
                }
            ) from syntaxError
        except Exception as exc:
            raise ValidationError(
                {'definition': 'An error occurred when compiling the definition'}
            ) from exc


class ScannerRule(AbstractScannerRule):
    action = models.PositiveSmallIntegerField(
        choices=ACTIONS.items(), default=NO_ACTION
    )
    is_active = models.BooleanField(
        default=True,
        help_text=(
            'When unchecked, the scanner results will not be bound to this '
            'rule and the action will not be executed.'
        ),
    )

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
    model_version = models.CharField(max_length=30, null=True)
    has_matches = models.BooleanField(null=True)
    state = models.PositiveSmallIntegerField(
        choices=RESULT_STATES.items(), null=True, blank=True, default=UNKNOWN
    )

    class Meta(AbstractScannerResult.Meta):
        db_table = 'scanners_results'
        constraints = [
            models.UniqueConstraint(
                fields=('upload', 'scanner', 'version'),
                name='scanners_results_upload_id_scanner_version_id_ad9eb8a6_uniq',
            )
        ]
        indexes = [
            models.Index(fields=('state',)),
            models.Index(fields=('has_matches',)),
        ]

    @classproperty
    def rule_model(self):
        return self.matched_rules.rel.model

    def get_rules_queryset(self):
        # See: https://github.com/mozilla/addons-server/issues/13143
        return super().get_rules_queryset().filter(is_active=True)

    def save(self, *args, **kwargs):
        matched_rules = self.get_rules_queryset()
        self.has_matches = bool(matched_rules)
        # Save the instance first...
        super().save(*args, **kwargs)
        # ...then add the associated rules.
        for scanner_rule in matched_rules:
            self.matched_rules.add(scanner_rule)

    def can_report_feedback(self):
        return self.state == UNKNOWN

    def can_revert_feedback(self):
        return self.state != UNKNOWN

    @classmethod
    def run_action(cls, version):
        """Try to find and execute an action for a given version, based on the
        scanner results and associated rules.

        If an action is found, it is run synchronously from this method, not in
        a task.
        """
        log.info('Checking rules and actions for version %s.', version.pk)

        if version.addon.type != ADDON_EXTENSION:
            log.info(
                'Not running action(s) on version %s which belongs to a non-extension.',
                version.pk,
            )
            return

        result_query_name = cls._meta.get_field('matched_rules').related_query_name()

        rule = (
            cls.rule_model.objects.filter(
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
            DELAY_AUTO_APPROVAL_INDEFINITELY_AND_RESTRICT_FUTURE_APPROVALS: (
                _delay_auto_approval_indefinitely_and_restrict_future_approvals
            ),
            DISABLE_AND_BLOCK: _disable_and_block,
        }

        action_function = ACTION_FUNCTIONS.get(action_id, None)

        if not action_function:
            raise Exception('no implementation for action %s' % action_id)

        # We have a valid action to execute, so let's do it!
        log.info('Starting action "%s" for version %s.', action_name, version.pk)
        action_function(version=version, rule=rule)
        log.info('Ending action "%s" for version %s.', action_name, version.pk)


class ScannerMatch(ModelBase):
    result = models.ForeignKey(ScannerResult, on_delete=models.CASCADE)
    rule = models.ForeignKey(ScannerRule, on_delete=models.CASCADE)


class ImproperScannerQueryRuleStateError(ValueError):
    pass


class ScannerQueryRule(AbstractScannerRule):
    scanner = models.PositiveSmallIntegerField(
        choices=((YARA, 'yara'), (NARC, 'narc')),
    )
    state = models.PositiveSmallIntegerField(
        choices=QUERY_RULE_STATES.items(), default=NEW
    )
    run_on_disabled_addons = models.BooleanField(
        default=False,
        help_text='Run this rule on add-ons that have been force-disabled as well.',
    )
    run_on_current_version_only = models.BooleanField(
        default=False,
        help_text=(
            'Run this rule on the latest currently publicly listed version of '
            'each add-on only.'
        ),
    )
    run_on_specific_channel = models.PositiveSmallIntegerField(
        default=None,
        null=True,
        blank=True,
        help_text='Run this rule on versions in the specific channel only.',
        choices=[(None, '')] + list(amo.CHANNEL_CHOICES.items()),
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
                return f'{rate:.2f}%'
        return None


class ScannerQueryResult(AbstractScannerResult):
    # Note: ScannerResult uses a M2M called 'matched_rules', but here we don't
    # need a M2M because there will always be a single rule for each result, so
    # we have a single FK called 'matched_rule' (singular).
    matched_rule = models.ForeignKey(
        ScannerQueryRule, on_delete=models.CASCADE, related_name='results'
    )
    was_blocked = models.BooleanField(null=True, default=None)

    class Meta(AbstractScannerResult.Meta):
        db_table = 'scanners_query_results'
        indexes = [
            models.Index(fields=('was_blocked',)),
        ]

    @classproperty
    def rule_model(cls):
        return cls.matched_rule.field.related_model

    def save(self, *args, **kwargs):
        if self.results:
            self.matched_rule = self.get_rules_queryset().get()
        super().save(*args, **kwargs)
