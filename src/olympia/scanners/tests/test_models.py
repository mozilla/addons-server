import pytest

from django.core.exceptions import ValidationError
from django.test.utils import override_settings
from unittest import mock

from olympia.amo.tests import TestCase, addon_factory
from olympia.constants.scanners import CUSTOMS, WAT, YARA, FALSE_POSITIVE
from olympia.files.models import FileUpload
from olympia.scanners.models import ScannerResult, ScannerRule


class FakeYaraMatch(object):
    def __init__(self, rule, tags, meta):
        self.rule = rule
        self.tags = tags
        self.meta = meta


class TestScannerResult(TestCase):
    def create_file_upload(self):
        addon = addon_factory()
        return FileUpload.objects.create(addon=addon)

    def create_customs_result(self):
        upload = self.create_file_upload()
        return ScannerResult.objects.create(upload=upload, scanner=CUSTOMS)

    def create_wat_result(self):
        upload = self.create_file_upload()
        return ScannerResult.objects.create(upload=upload, scanner=WAT)

    def create_fake_yara_match(
        self, rule='some-yara-rule', tags=None, description='some description'
    ):
        return FakeYaraMatch(
            rule=rule, tags=tags or [], meta={'description': description}
        )

    def create_yara_result(self):
        upload = self.create_file_upload()
        return ScannerResult.objects.create(upload=upload, scanner=YARA)

    def test_create(self):
        upload = self.create_file_upload()

        result = ScannerResult.objects.create(upload=upload, scanner=CUSTOMS)

        assert result.id is not None
        assert result.upload == upload
        assert result.scanner == CUSTOMS
        assert result.results == []
        assert result.version is None
        assert result.has_matches is False

    def test_create_different_entries_for_a_single_upload(self):
        upload = self.create_file_upload()

        customs_result = ScannerResult.objects.create(
            upload=upload, scanner=CUSTOMS
        )
        wat_result = ScannerResult.objects.create(upload=upload, scanner=WAT)

        assert customs_result.scanner == CUSTOMS
        assert wat_result.scanner == WAT

    def test_add_yara_result(self):
        result = self.create_yara_result()
        match = self.create_fake_yara_match()

        result.add_yara_result(
            rule=match.rule, tags=match.tags, meta=match.meta
        )

        assert result.results == [
            {'rule': match.rule, 'tags': match.tags, 'meta': match.meta}
        ]

    def test_save_set_has_matches(self):
        result = self.create_yara_result()
        rule = ScannerRule.objects.create(
            name='some rule name', scanner=result.scanner
        )

        result.has_matches = None
        result.save()
        assert result.has_matches is False

        result.has_matches = None
        result.results = [{'rule': rule.name}]  # Fake match
        result.save()
        assert result.has_matches is True

    def test_upload_constraint(self):
        upload = self.create_file_upload()
        result = ScannerResult.objects.create(upload=upload, scanner=CUSTOMS)

        upload.delete()
        result.refresh_from_db()

        assert result.upload is None

    def test_extract_rule_names_with_no_yara_results(self):
        result = self.create_yara_result()
        assert result.extract_rule_names() == []

    def test_extract_rule_names_with_yara_results(self):
        result = self.create_yara_result()
        rule1 = 'rule-1'
        rule2 = 'rule-2'

        for rule in [rule1, rule2]:
            match = self.create_fake_yara_match(rule=rule)
            result.add_yara_result(
                rule=match.rule, tags=match.tags, meta=match.meta
            )

        assert result.extract_rule_names() == [rule1, rule2]

    def test_extract_rule_names_returns_unique_list(self):
        result = self.create_yara_result()
        rule1 = 'rule-1'
        rule2 = 'rule-2'

        for rule in [rule1, rule2, rule1, rule2]:
            match = self.create_fake_yara_match(rule=rule)
            result.add_yara_result(
                rule=match.rule, tags=match.tags, meta=match.meta
            )

        assert result.extract_rule_names() == [rule1, rule2]

    def test_extract_rule_names_returns_empty_list_for_unsupported_scanner(
        self
    ):
        upload = self.create_file_upload()
        result = ScannerResult.objects.create(upload=upload, scanner=WAT)
        assert result.extract_rule_names() == []

    def test_extract_rule_names_with_no_customs_matched_rules_attribute(self):
        result = self.create_customs_result()
        result.results = {}
        assert result.extract_rule_names() == []

    def test_extract_rule_names_with_no_customs_results(self):
        result = self.create_customs_result()
        result.results = {'matchedRules': []}
        assert result.extract_rule_names() == []

    def test_extract_rule_names_with_customs_results(self):
        result = self.create_customs_result()
        rules = ['rule-1', 'rule-2']
        result.results = {'matchedRules': rules}
        assert result.extract_rule_names() == rules

    def test_get_scanner_name(self):
        result = self.create_customs_result()
        assert result.get_scanner_name() == 'customs'

    def test_get_pretty_results(self):
        result = self.create_customs_result()
        result.results = {'foo': 'bar'}
        assert result.get_pretty_results() == '{\n  "foo": "bar"\n}'

    def test_get_customs_git_repository(self):
        result = self.create_customs_result()
        git_repo = 'some git repo'

        with override_settings(CUSTOMS_GIT_REPOSITORY=git_repo):
            assert result.get_git_repository() == git_repo

    def test_get_yara_git_repository(self):
        result = self.create_yara_result()
        git_repo = 'some git repo'

        with override_settings(YARA_GIT_REPOSITORY=git_repo):
            assert result.get_git_repository() == git_repo

    def test_get_git_repository_returns_none_if_not_supported(self):
        result = self.create_wat_result()
        assert result.get_git_repository() is None

    def test_can_report_feedback_is_false_when_there_is_no_match(self):
        result = self.create_customs_result()
        assert not result.can_report_feedback()

    def test_can_report_feedback(self):
        result = self.create_customs_result()
        result.has_matches = True
        assert result.can_report_feedback()

    def test_can_report_feedback_is_false_when_state_is_not_unknown(self):
        result = self.create_customs_result()
        result.has_matches = True
        result.state = FALSE_POSITIVE
        assert not result.can_report_feedback()

    def test_can_report_feedback_is_false_when_scanner_is_wat(self):
        result = self.create_wat_result()
        result.has_matches = True
        assert not result.can_report_feedback()

    def test_can_revert_feedback_for_triaged_result(self):
        result = self.create_yara_result()
        result.has_matches = True
        result.state = FALSE_POSITIVE
        assert result.can_revert_feedback()

    def test_cannot_revert_feedback_for_untriaged_result(self):
        result = self.create_yara_result()
        result.has_matches = True
        assert not result.can_revert_feedback()


class TestScannerRule(TestCase):
    def test_clean_raises_for_yara_rule_without_a_definition(self):
        rule = ScannerRule(name='some_rule', scanner=YARA)

        with pytest.raises(ValidationError, match=r'should have a definition'):
            rule.clean()

    def test_clean_raises_for_yara_rule_without_same_rule_name(self):
        rule = ScannerRule(
            name='some_rule', scanner=YARA, definition='rule x {}'
        )

        with pytest.raises(ValidationError, match=r'should match the name of'):
            rule.clean()

    def test_clean_raises_when_yara_rule_has_two_rules(self):
        rule = ScannerRule(
            name='some_rule',
            scanner=YARA,
            definition='rule some_rule {} rule foo {}',
        )

        with pytest.raises(ValidationError, match=r'Only one Yara rule'):
            rule.clean()

    def test_clean_raises_when_yara_rule_is_invalid(self):
        rule = ScannerRule(
            name='some_rule',
            scanner=YARA,
            # Invalid because there is no `condition`.
            definition='rule some_rule {}',
        )

        with pytest.raises(
            ValidationError, match=r'The definition is not valid: line 1'
        ):
            rule.clean()

    @mock.patch('yara.compile')
    def test_clean_raises_generic_error_when_yara_compile_failed(
        self, yara_compile_mock
    ):
        rule = ScannerRule(
            name='some_rule',
            scanner=YARA,
            definition='rule some_rule { condition: true }'
        )
        yara_compile_mock.side_effect = Exception()

        with pytest.raises(ValidationError, match=r'An error occurred'):
            rule.clean()
