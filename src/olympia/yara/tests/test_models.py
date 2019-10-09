from olympia.amo.tests import TestCase, addon_factory

from olympia.files.models import FileUpload
from olympia.yara.models import YaraResult


class FakeYaraMatch(object):

    def __init__(self, rule, tags, meta):
        self.rule = rule
        self.tags = tags
        self.meta = meta


class TestYaraResult(TestCase):
    def create_file_upload(self):
        addon = addon_factory()
        return FileUpload.objects.create(addon=addon)

    def create_fake_yara_match(self,
                               rule='some-yara-rule',
                               tags=None,
                               description='some description'):
        return FakeYaraMatch(
            rule=rule,
            tags=tags or [],
            meta={'description': description}
        )

    def create_yara_result(self):
        upload = self.create_file_upload()
        return YaraResult.objects.create(upload=upload)

    def test_create(self):
        upload = self.create_file_upload()

        result = YaraResult.objects.create(upload=upload)

        assert result.id is not None
        assert result.upload == upload
        assert result.matches == []
        assert result.version is None
        assert result.has_matches is False

    def test_add_match(self):
        result = self.create_yara_result()
        match = self.create_fake_yara_match()

        result.add_match(rule=match.rule, tags=match.tags, meta=match.meta)

        assert result.matches == [{
            'rule': match.rule,
            'tags': match.tags,
            'meta': match.meta,
        }]
        assert result.has_matches is True

    def test_save_set_has_matches_if_none(self):
        result = self.create_yara_result()
        result.has_matches = None
        result.save()
        assert result.has_matches is False

        result.has_matches = None
        result.matches = [{}]  # Fake match
        result.save()
        assert result.has_matches is True

    def test_upload_constraint(self):
        upload = self.create_file_upload()
        result = YaraResult.objects.create(upload=upload)

        upload.delete()
        result.refresh_from_db()

        assert result.upload is None

    def test_empty_matched_rules(self):
        result = self.create_yara_result()
        assert result.matched_rules == []

    def test_matched_rules(self):
        result = self.create_yara_result()
        rule1 = 'rule-1'
        rule2 = 'rule-2'

        for rule in [rule1, rule2]:
            match = self.create_fake_yara_match(rule=rule)
            result.add_match(rule=match.rule, tags=match.tags, meta=match.meta)

        assert result.matched_rules == [rule1, rule2]

    def test_matched_rules_returns_unique_list(self):
        result = self.create_yara_result()
        rule1 = 'rule-1'
        rule2 = 'rule-2'

        for rule in [rule1, rule2, rule1, rule2]:
            match = self.create_fake_yara_match(rule=rule)
            result.add_match(rule=match.rule, tags=match.tags, meta=match.meta)

        assert result.matched_rules == [rule1, rule2]
