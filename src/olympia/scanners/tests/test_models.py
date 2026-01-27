import uuid
from datetime import datetime
from unittest import mock

from django.core.exceptions import ValidationError
from django.test.utils import override_settings

import pytest
import time_machine

from olympia import amo
from olympia.amo.tests import TestCase, addon_factory, user_factory
from olympia.constants.scanners import (
    ABORTED,
    ABORTING,
    COMPLETED,
    CUSTOMS,
    FALSE_POSITIVE,
    NARC,
    NEW,
    RUNNING,
    SCANNERS,
    SCHEDULED,
    UNKNOWN,
    YARA,
)
from olympia.files.models import FileUpload
from olympia.scanners.models import (
    ImproperScannerQueryRuleStateError,
    ScannerQueryResult,
    ScannerQueryRule,
    ScannerResult,
    ScannerRule,
    ScannerWebhook,
)
from olympia.users.models import UserProfile


class FakeYaraMatch:
    def __init__(self, rule, tags, meta):
        self.rule = rule
        self.tags = tags
        self.meta = meta


class TestScannerResultMixin:
    __test__ = False

    def create_result(self, *args, **kwargs):
        return self.model.objects.create(*args, **kwargs)

    def create_fake_yara_match(
        self,
        rule='some-yara-rule',
        tags=None,
        description='some description',
        filename='some/file.js',
    ):
        return FakeYaraMatch(
            rule=rule,
            tags=tags or [],
            meta={
                'description': description,
                'filename': filename,
            },
        )

    def test_add_yara_result(self):
        result = self.create_result(scanner=YARA)
        match = self.create_fake_yara_match()

        result.add_yara_result(rule=match.rule, tags=match.tags, meta=match.meta)

        assert result.results == [
            {'rule': match.rule, 'tags': match.tags, 'meta': match.meta}
        ]

    def test_extract_rule_names_with_no_yara_results(self):
        result = self.create_result(scanner=YARA)
        assert result.extract_rule_names() == []

    def test_extract_rule_names_with_yara_results(self):
        result = self.create_result(scanner=YARA)
        rule1 = 'rule-1'
        rule2 = 'rule-2'

        for rule in [rule1, rule2]:
            match = self.create_fake_yara_match(rule=rule)
            result.add_yara_result(rule=match.rule, tags=match.tags, meta=match.meta)

        assert result.extract_rule_names() == [rule1, rule2]

    def test_extract_rule_names_with_narc_results(self):
        result = self.create_result(scanner=NARC)
        rule1 = 'rule-1'
        rule2 = 'rule-2'

        for rule in [rule1, rule2]:
            result.results.append({'rule': rule, 'meta': {'whatever': 'eh'}})

        assert result.extract_rule_names() == [rule1, rule2]

    def test_extract_rule_names_returns_unique_list(self):
        result = self.create_result(scanner=YARA)
        rule1 = 'rule-1'
        rule2 = 'rule-2'

        for rule in [rule1, rule2, rule1, rule2]:
            match = self.create_fake_yara_match(rule=rule)
            result.add_yara_result(rule=match.rule, tags=match.tags, meta=match.meta)

        assert result.extract_rule_names() == [rule1, rule2]

    def test_extract_rule_names_with_no_customs_matched_rules_attribute(self):
        result = self.create_result(scanner=CUSTOMS)
        result.results = {}
        assert result.extract_rule_names() == []

    def test_extract_rule_names_with_no_customs_results(self):
        result = self.create_result(scanner=CUSTOMS)
        result.results = {'matchedRules': []}
        assert result.extract_rule_names() == []

    def test_extract_rule_names_with_customs_results(self):
        result = self.create_result(scanner=CUSTOMS)
        rules = ['rule-1', 'rule-2']
        result.results = {'matchedRules': rules}
        assert result.extract_rule_names() == rules

    def test_get_scanner_name(self):
        result = self.create_result(scanner=CUSTOMS)
        assert result.get_scanner_name() == 'customs'

    def test_get_pretty_results(self):
        result = self.create_result(scanner=CUSTOMS)
        result.results = {'foo': 'bar'}
        assert result.get_pretty_results() == '{\n  "foo": "bar"\n}'

    def test_get_customs_git_repository(self):
        result = self.create_result(scanner=CUSTOMS)
        git_repo = 'some git repo'

        with override_settings(CUSTOMS_GIT_REPOSITORY=git_repo):
            assert result.get_git_repository() == git_repo

    def test_get_git_repository_returns_none_if_not_supported(self):
        result = self.create_result(scanner=CUSTOMS)
        assert result.get_git_repository() is None

    def test_get_files_and_data_by_matched_rules_with_no_yara_results(self):
        result = self.create_result(scanner=YARA)
        assert result.get_files_and_data_by_matched_rules() == {}

    def test_get_files_and_data_by_matched_rules_for_yara(self):
        result = self.create_result(scanner=YARA)
        rule1 = 'rule-1'
        file1 = 'file/1.js'
        match1 = self.create_fake_yara_match(rule=rule1, filename=file1)
        result.add_yara_result(rule=match1.rule, tags=match1.tags, meta=match1.meta)
        rule2 = 'rule-2'
        file2 = 'file/2.js'
        match2 = self.create_fake_yara_match(rule=rule2, filename=file2)
        result.add_yara_result(rule=match2.rule, tags=match2.tags, meta=match2.meta)
        # rule1 with file2
        match3 = self.create_fake_yara_match(rule=rule1, filename=file2)
        result.add_yara_result(rule=match3.rule, tags=match3.tags, meta=match3.meta)
        assert result.get_files_and_data_by_matched_rules() == {
            rule1: [{'filename': file1}, {'filename': file2}],
            rule2: [{'filename': file2}],
        }

    def test_get_files_and_data_by_matched_rules_no_file_somehow(self):
        result = self.create_result(scanner=YARA)
        rule = self.rule_model.objects.create(name='foobar', scanner=YARA)
        result.add_yara_result(rule=rule.name)
        result.save()
        assert result.get_files_and_data_by_matched_rules() == {
            'foobar': [{'filename': '???'}],
        }

    def test_get_files_and_data_by_matched_rules_with_no_customs_results(self):
        result = self.create_result(scanner=CUSTOMS)
        result.results = {'matchedRules': []}
        assert result.get_files_and_data_by_matched_rules() == {}

    def test_get_files_and_data_by_matched_rules_for_customs(self):
        result = self.create_result(scanner=CUSTOMS)
        file1 = 'file/1.js'
        rule1 = 'rule1'
        file2 = 'file/2.js'
        rule2 = 'rule2'
        file3 = 'file/3.js'
        rule3 = 'rule3'
        file4 = 'file/4.js'
        result.results = {
            'scanMap': {
                file1: {
                    rule1: {
                        'RULE_HAS_MATCHED': True,
                    },
                    rule2: {},
                    # no rule3
                },
                file2: {
                    rule1: {
                        'RULE_HAS_MATCHED': False,
                    },
                    rule2: {},
                    # no rule3
                },
                file3: {
                    rule1: {},
                    rule2: {},
                    rule3: {
                        'RULE_HAS_MATCHED': True,
                        'EXTRA': [
                            'some',
                            'thing',
                        ],
                    },
                },
                file4: {
                    # no rule1 or rule2
                    rule3: {
                        'RULE_HAS_MATCHED': True,
                    },
                },
                '__GLOBAL__': {
                    rule1: {
                        'RULE_HAS_MATCHED': True,
                        'MAWR_DATA': [
                            'foo',
                            'bar',
                        ],
                    }
                },
            }
        }
        assert result.get_files_and_data_by_matched_rules() == {
            rule1: [
                {'data': {}, 'filename': file1},
                {'data': {'MAWR_DATA': ['foo', 'bar']}, 'filename': ''},
            ],
            rule3: [
                {'data': {'EXTRA': ['some', 'thing']}, 'filename': file3},
                {'data': {}, 'filename': file4},
            ],
        }

    def test_get_files_and_data_by_matched_rules_for_narc(self):
        result = self.create_result(scanner=NARC)
        rule = self.rule_model.objects.create(name='foobar', scanner=NARC)
        result.results = [
            {
                'rule': rule.name,
                'meta': {
                    'locale': None,
                    'source': 'something',
                    'pattern': 'secret.*pattern',
                    'string': 'Some string',
                    'span': (0, 42),
                },
            }
        ]
        result.save()
        assert result.get_files_and_data_by_matched_rules() == {
            'foobar': [
                {
                    # Pattern and span should not appear.
                    'locale': None,
                    'source': 'something',
                    'string': 'Some string',
                },
            ],
        }


class TestScannerResult(TestScannerResultMixin, TestCase):
    __test__ = True
    model = ScannerResult
    rule_model = ScannerRule

    def create_file_upload(self):
        addon = addon_factory()
        return FileUpload.objects.create(
            addon=addon,
            user=user_factory(),
            ip_address='1.2.3.4',
            source=amo.UPLOAD_SOURCE_DEVHUB,
            channel=amo.CHANNEL_LISTED,
        )

    def create_result(self, *args, **kwargs):
        kwargs['upload'] = self.create_file_upload()
        return super().create_result(*args, **kwargs)

    def test_create(self):
        upload = self.create_file_upload()

        result = self.model.objects.create(upload=upload, scanner=CUSTOMS)

        assert result.id is not None
        assert result.upload == upload
        assert result.scanner == CUSTOMS
        assert result.results == []
        assert result.version is None
        assert result.has_matches is False

    def test_create_different_entries_for_a_single_upload(self):
        upload = self.create_file_upload()

        customs_result = self.model.objects.create(upload=upload, scanner=CUSTOMS)
        yara_result = self.model.objects.create(upload=upload, scanner=YARA)

        assert customs_result.scanner == CUSTOMS
        assert yara_result.scanner == YARA

    def test_upload_constraint(self):
        upload = self.create_file_upload()
        result = self.model.objects.create(upload=upload, scanner=CUSTOMS)

        upload.delete()
        result.refresh_from_db()

        assert result.upload is None

    def test_can_report_feedback(self):
        result = self.create_result(scanner=CUSTOMS)
        assert result.can_report_feedback()

    def test_can_report_feedback_is_false_when_state_is_not_unknown(self):
        result = self.create_result(scanner=CUSTOMS)
        result.state = FALSE_POSITIVE
        assert not result.can_report_feedback()

    def test_can_revert_feedback_for_triaged_result(self):
        result = self.create_result(scanner=YARA)
        result.state = FALSE_POSITIVE
        assert result.can_revert_feedback()

    def test_cannot_revert_feedback_for_untriaged_result(self):
        result = self.create_result(scanner=YARA)
        assert result.state == UNKNOWN
        assert not result.can_revert_feedback()

    def test_save_set_has_matches(self):
        result = self.create_result(scanner=YARA)
        rule = self.rule_model.objects.create(
            name='some rule name', scanner=result.scanner
        )

        result.has_matches = None
        result.save()
        assert result.has_matches is False

        result.has_matches = None
        result.results = [{'rule': rule.name}]  # Fake match
        result.save()
        assert result.has_matches is True

    def test_save_ignores_disabled_rules(self):
        result = self.create_result(scanner=YARA)
        rule = self.rule_model.objects.create(
            name='some rule name', scanner=result.scanner, is_active=False
        )

        result.has_matches = None
        result.results = [{'rule': rule.name}]  # Fake match
        result.save()
        assert result.has_matches is False


class TestScannerQueryResult(TestScannerResultMixin, TestCase):
    __test__ = True
    model = ScannerQueryResult
    rule_model = ScannerQueryRule

    def create_result(self, *args, **kwargs):
        # We can't save ScannerQueryResults in database without a rule, so for
        # this test class create_result() is overridden to not save the result
        # initially - it will be saved later when adding the result data.
        return self.model(*args, **kwargs)


class TestScannerRuleMixin:
    __test__ = False

    def test_str(self):
        result = self.model(name='Fôo')
        assert str(result) == 'Fôo'
        result.pretty_name = 'Bär'
        assert str(result) == 'Bär'

    def test_clean_raises_for_narc_rule_without_a_definition(self):
        rule = self.model(name='some_rule', scanner=NARC)

        with pytest.raises(ValidationError, match=r'should have a definition'):
            rule.clean()

    def test_clean_raises_for_narc_rule_that_doesnt_compile(self):
        rule = self.model(
            name='some_rule',
            scanner=NARC,
            definition=r'^test\Y',  # Invalid escape sequence in regexp
        )

        with pytest.raises(ValidationError, match=r'error occurred when compiling'):
            rule.clean()

    def test_clean_raises_for_yara_rule_without_a_definition(self):
        rule = self.model(name='some_rule', scanner=YARA)

        with pytest.raises(ValidationError, match=r'should have a definition'):
            rule.clean()

    def test_clean_raises_for_yara_rule_without_same_rule_name(self):
        rule = self.model(name='some_rule', scanner=YARA, definition='rule x {}')

        with pytest.raises(ValidationError, match=r'should match the name of'):
            rule.clean()

    def test_clean_raises_when_yara_rule_has_two_rules(self):
        rule = self.model(
            name='some_rule',
            scanner=YARA,
            definition='rule some_rule {} rule foo {}',
        )

        with pytest.raises(ValidationError, match=r'Only one Yara rule'):
            rule.clean()

    def test_clean_raises_when_yara_rule_is_invalid(self):
        rule = self.model(
            name='some_rule',
            scanner=YARA,
            # Invalid because there is no `condition`.
            definition='rule some_rule {}',
        )

        with pytest.raises(
            ValidationError, match=r'The definition is not valid: line 1'
        ):
            rule.clean()

    def test_clean_supports_our_external_variables(self):
        externals = self.model.get_yara_externals()
        assert externals
        conditions = ' and '.join(externals)
        rule = self.model(
            name='some_rule',
            scanner=YARA,
            definition='rule some_rule { condition: %s}' % conditions,
        )
        rule.clean()  # Shouldn't raise, the externals are automatically added.

    @mock.patch('yara.compile')
    def test_clean_raises_generic_error_when_yara_compile_failed(
        self, yara_compile_mock
    ):
        rule = self.model(
            name='some_rule',
            scanner=YARA,
            definition='rule some_rule { condition: true }',
        )
        yara_compile_mock.side_effect = Exception()

        with pytest.raises(ValidationError, match=r'An error occurred'):
            rule.clean()


class TestScannerRule(TestScannerRuleMixin, TestCase):
    __test__ = True
    model = ScannerRule

    def test_scanner_choices(self):
        field = self.model._meta.get_field('scanner')
        assert field.choices == SCANNERS.items()


class TestScannerQueryRule(TestScannerRuleMixin, TestCase):
    __test__ = True
    model = ScannerQueryRule

    def test_scanner_choices(self):
        # Code search only supports yara for now.
        field = self.model._meta.get_field('scanner')
        assert field.choices == ((YARA, 'yara'), (NARC, 'narc'))

    @mock.patch('olympia.amo.celery.app.GroupResult.restore')
    def test_completed_task_count(self, restore_mock):
        restore_mock.return_value.completed_count.return_value = 42
        rule = ScannerQueryRule(state=RUNNING, celery_group_result_id=str(uuid.uuid4()))
        assert rule._get_completed_tasks_count() == 42

        restore_mock.return_value = None
        assert rule._get_completed_tasks_count() is None

    def test_completed_task_count_no_group_id(self):
        rule = ScannerQueryRule(state=RUNNING, celery_group_result_id=None)
        assert rule._get_completed_tasks_count() is None

    @mock.patch.object(ScannerQueryRule, '_get_completed_tasks_count')
    def test_completion_rate(self, _get_completed_tasks_count_mock):
        rule = ScannerQueryRule(state=RUNNING, task_count=10000)

        _get_completed_tasks_count_mock.return_value = None
        assert rule.completion_rate() is None

        _get_completed_tasks_count_mock.return_value = 0
        assert rule.completion_rate() == '0.00%'

        _get_completed_tasks_count_mock.return_value = 1000
        assert rule.completion_rate() == '10.00%'

        _get_completed_tasks_count_mock.return_value = 3333
        assert rule.completion_rate() == '33.33%'

        _get_completed_tasks_count_mock.return_value = 10000
        assert rule.completion_rate() == '100.00%'

        rule.task_count = 0
        assert rule.completion_rate() is None

    def test_completion_rate_not_running(self):
        rule = ScannerQueryRule(state=NEW, task_count=10000)
        assert rule.completion_rate() is None

        rule.state = SCHEDULED
        assert rule.completion_rate() is None

        rule.state = ABORTING
        assert rule.completion_rate() is None

        rule.state = ABORTED
        assert rule.completion_rate() is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    'current_state,target_state',
    [
        (NEW, SCHEDULED),
        (SCHEDULED, RUNNING),
        (NEW, ABORTING),  # Technically not exposed through the admin yet.
        (SCHEDULED, ABORTING),  # Technically not exposed through the admin yet.
        (RUNNING, ABORTING),
        (ABORTING, ABORTED),
        (RUNNING, COMPLETED),
    ],
)
def test_query_rule_change_state_to_valid(current_state, target_state):
    rule = ScannerQueryRule(name='some_rule', scanner=YARA)
    rule.state = current_state
    with time_machine.travel('2020-04-08 15:16:23.42', tick=False):
        rule.change_state_to(target_state)
        now = datetime.now()
    if target_state == COMPLETED:
        assert rule.completed == now
        assert rule.completed != datetime.now()
    else:
        assert rule.completed is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    'current_state,target_state',
    [
        (NEW, RUNNING),  # Should go through SCHEDULED first to work.
        (NEW, ABORTED),  # Should go through ABORTING first to work.
        (NEW, COMPLETED),  # Should go through RUNNING first to work.
        (SCHEDULED, NEW),  # Can't reset to NEW.
        (SCHEDULED, ABORTED),  # Should go through ABORTING first to work.
        (SCHEDULED, COMPLETED),  # Should go through RUNNING first to work.
        (RUNNING, NEW),  # Can't reset to NEW.
        (RUNNING, ABORTED),  # Should go through ABORTING first to work.
        (RUNNING, SCHEDULED),  # Can't reset to SCHEDULED
        (ABORTING, NEW),  # Can't reset to NEW.
        (ABORTING, RUNNING),  # Can't reset to RUNNING
        (ABORTING, SCHEDULED),  # Can't reset to SCHEDULED
        (ABORTED, NEW),  # Can't reset to NEW.
        (ABORTED, RUNNING),  # Can't reset to RUNNING.
        (ABORTED, SCHEDULED),  # Can't reset to SCHEDULED
        (COMPLETED, NEW),  # Can't reset to... anything, it's completed!
        (COMPLETED, RUNNING),  # As above.
        (COMPLETED, ABORTED),  # As above.
        (COMPLETED, ABORTING),  # As above.
        (COMPLETED, SCHEDULED),  # As above.
    ],
)
def test_query_rule_change_state_to_invalid(current_state, target_state):
    rule = ScannerQueryRule(name='some_rule', scanner=YARA)
    rule.state = current_state
    with pytest.raises(ImproperScannerQueryRuleStateError):
        rule.change_state_to(target_state)
    # Manually changing state doesn't affect 'completed' property, and since
    # changing through change_state_to() failed before it should always be
    # None in this test.
    assert rule.completed is None


class TestScannerWebhook(TestCase):
    def test_save_creates_a_service_account(self):
        name = 'some name'
        webhook = ScannerWebhook(name=name, url='https://example.com', api_key='secret')
        with self.assertRaises(UserProfile.DoesNotExist):
            UserProfile.objects.get_service_account(name=webhook.service_account_name)

        webhook.save()

        user = UserProfile.objects.get_service_account(
            name=webhook.service_account_name
        )
        assert user.pk is not None
        assert user.notes == (
            f'Service account automatically created for the "{name}" scanner webhook.'
        )
