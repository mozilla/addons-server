from olympia.amo.tests import TestCase, addon_factory

from olympia.files.models import FileUpload
from olympia.yara.models import YaraResult


class TestYaraResult(TestCase):
    def create_file_upload(self):
        addon = addon_factory()
        return FileUpload.objects.create(addon=addon)

    def test_create(self):
        upload = self.create_file_upload()

        result = YaraResult.objects.create(upload=upload)

        assert result.id is not None
        assert result.upload == upload
        assert result.matches == []
        assert result.version is None

    def test_add_match(self):
        upload = self.create_file_upload()
        result = YaraResult.objects.create(upload=upload)

        rule = 'some-yara-rule'
        tags = ['foo']
        meta = {'description': 'some description for some-yara-rule'}
        result.add_match(rule=rule, tags=tags, meta=meta)

        assert result.matches == [{
            'rule': rule,
            'tags': tags,
            'meta': meta,
        }]

    def test_upload_constraint(self):
        upload = self.create_file_upload()
        result = YaraResult.objects.create(upload=upload)

        upload.delete()
        result.refresh_from_db()

        assert result.upload is None
