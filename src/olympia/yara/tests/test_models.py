from olympia.amo.tests import TestCase, addon_factory

from olympia.files.models import FileUpload
from olympia.yara.models import YaraResult


class TestYaraResult(TestCase):
    def test_create(self):
        addon = addon_factory()
        upload = FileUpload.objects.create(addon=addon)

        result = YaraResult.objects.create(upload=upload)

        assert result.id is not None
        assert result.upload == upload
        assert result.matches == []
        assert result.version is None

    def test_add_match(self):
        addon = addon_factory()
        upload = FileUpload.objects.create(addon=addon)
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
