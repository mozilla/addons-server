from olympia.amo.tests import TestCase, addon_factory

from olympia.constants.scanners import CUSTOMS, WAT, YARA
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
